# NexusAPI — Decision Log

## Question 1: Why does the credit system use a transaction ledger instead of a balance column?

When I first thought about storing credits, the obvious approach was a simple
balance column on the organisations table — just a number that goes up when
credits are added and down when they're spent. But I quickly realised this
would break under concurrent usage.

The core problem is that two requests can read the same balance at the same
time. If an organisation has 25 credits and two API calls arrive simultaneously,
both reads return 25, both decide that's enough, and both deduct — leaving
the balance at -25. That's a double-spend, and there's no way to detect it
after the fact.

The ledger approach solves this by never updating a number directly. Instead,
every credit movement is written as a new row — positive for grants, negative
for deductions — and the current balance is always derived by summing all rows
for that organisation. This means the balance is computed from facts that
already happened, not from a number someone could accidentally overwrite.

The other reason I preferred this approach is auditability. With a balance
column, if a user says "I never used 25 credits yesterday", there's nothing
to show them. With a ledger, every transaction has a timestamp, a reason, and
the user who triggered it. That's much easier to debug and explain.

The tradeoff is that every balance check requires a SUM query across all
transactions for that organisation. As transaction history grows this gets
slower, and at high scale I would add a cached balance column that gets
updated atomically alongside each transaction insert. But for this system,
the correctness benefit outweighs the performance cost.

## Question 2: How did you handle the simultaneous credit deduction problem?

This was the part I spent the most time thinking about. The scenario is: two
requests arrive at the exact same millisecond, the organisation has exactly 25
credits, and both requests cost 25 credits. Only one should succeed.

My first instinct was to handle this in application code — check the balance,
then deduct. But that has a gap: between the check and the deduction, another
request can slip through. Application-level checks don't help when two requests
are running at the same time in different async tasks.

The solution I used is PostgreSQL's SELECT FOR UPDATE. When deduct_credits
runs, the query that calculates the current balance adds a .with_for_update()
clause. This tells the database to lock the relevant rows while the transaction
is in progress. The first request acquires the lock and reads 25 credits. The
second request tries to run the same query but has to wait — it can't proceed
until the first request either commits or rolls back.

When the first request commits its deduction row, the lock releases. The second
request now runs, recalculates the balance (which is now 0), and raises
InsufficientCreditsError. Only one deduction happens.

I considered optimistic locking with a version column as an alternative — you
read the version, do your work, and only commit if the version hasn't changed.
But that requires retry logic on conflict, which adds complexity and can cause
requests to spin under high load. The SELECT FOR UPDATE approach is simpler to
reason about and easier to test.

## Question 3: What happens when the background worker fails after credits have been deducted?

When a summarise request comes in, credits are deducted immediately and a job
record is created with status "pending". If the ARQ worker crashes before
processing that job, the credits stay deducted and the job never reaches
"completed".

I decided not to implement automatic refunds. My reasoning was that a refund
system introduces more complexity than it solves at this stage. A refund needs
to be idempotent too — you can't accidentally refund twice — which means you
need the same kind of unique constraint and race condition handling as the
original deduction. Getting that right is a full feature on its own.

What I implemented instead is a scheduled cleanup job that runs every 60
seconds and marks any job that has been in "pending" or "running" state for
more than five minutes as "failed", with an error message that says the job
timed out and that credits were not automatically refunded. The job record
stays in the database permanently, so an admin can query for failed jobs and
issue manual refunds where needed.

The five minute threshold felt right — long enough that a slow but healthy job
won't get falsely marked as failed, but short enough that a user who queued a
job and got nothing back will hear about it before they notice.

In a production system I would build a proper refund queue on top of this, but
I wanted to be honest about what I actually implemented versus what I would add
next.

## Question 4: How does your idempotency implementation work, and where does it live?

Idempotency is handled in two places — application logic and database
constraints — because neither one alone is sufficient.

The application-level check happens at the very start of both product
endpoints, before any credits are touched. If the request includes an
Idempotency-Key header, we look up that key in the idempotency_records table
scoped to the current organisation and within the last 24 hours. If a matching
record exists, we return the stored response immediately. No credits are
deducted, no work is done.

If no record exists, the request proceeds normally. After a successful
response, the response body is saved to idempotency_records with the key and
organisation ID, so any future duplicate gets the same response.

The problem with only doing this in application code is concurrent requests.
Two identical requests can arrive before either has finished — both check the
table, both find nothing, and both proceed to deduct credits. To prevent this,
the credit_transactions table has a unique constraint on the idempotency_key
column. Even if two requests race through the application-level check, only
one can insert a transaction row with that key. The second gets an
IntegrityError, which we catch and handle by fetching and returning the
transaction that the first request committed.

I also prefixed the stored key with the organisation ID — so the actual stored
value is "org-uuid:user-provided-key". This means different organisations can
use the same key string without colliding. I discovered this bug during testing
when a second test account tried to reuse a key that the first account had
already used, and the database rejected it.

## Question 5: What would break first at 10x the current load, and what would you do about it?

The first thing to break would be the credit balance query. Right now, every
call to /api/analyse and /api/summarise runs a SUM across all credit
transaction rows for that organisation to check whether there are enough
credits. When an organisation is small and young this is fast. But as
transaction history grows and request volume increases, this query gets slower
on every single API call.

The fix I would reach for first is adding a cached balance column to the
organisations table. This column would be updated atomically inside the same
database transaction as every credit deduction or grant — so it's always
consistent with the ledger, and reading the balance becomes a single indexed
column lookup instead of a full aggregate. The tricky part is making sure the
cache update and the transaction insert always happen together, which requires
careful handling of rollbacks.

The second bottleneck would be the database connection pool. At 10x load with
async requests all hitting the database simultaneously, we'd start seeing
connection wait times. I would increase the pool size and look at connection
pooling at the infrastructure level — PgBouncer in front of Neon, for example.

Redis would likely be fine since it handles high throughput well, but if the
rate limiting keys started showing contention I would switch to a Redis cluster
setup.

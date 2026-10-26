# O4U API error contract

What the website and Stockroom actually receive over HTTP when something goes wrong. **Generated** by `backend/api_tests/run_local_stack.py`
(the full suite, test D5 plus the observed limit cases of F1/F2) against PostgREST in front of the migrations 0001-0009 - do not edit by hand;
rerun the suite to refresh it. Values are the exact status / `code` / `message` / `details` / `hint` of the JSON error body. Random ids in
`details` are shown as `<uuid>`. Local PostgREST version and test run: see `backend/api_tests/README.md`. A hosted Supabase project runs PostgREST
too, so database-error bodies are expected to have the same shape - NOT yet verified on the hosted project; gateway-level errors (missing apikey,
platform limits) are not covered here.

## Rules for the front ends

1. **Branch on HTTP status and `code`, show `message` only where listed below.** `code` is the PostgreSQL SQLSTATE (`P0001`, `PT429`, `42501` ...)
   or a PostgREST `PGRSTnnn` code. `message` for `P0001` / `PT429` from the three public functions is written for people and is safe to show.
2. **Never show** `details`, `hint`, or any message from `22xxx`, `23xxx`, `25xxx`, `57xxx`, `42xxx` or `PGRST*`: they carry table, constraint and key
   names (`23505` details include internal ids and UPI references). Show a generic "something went wrong, please try again or WhatsApp us".
3. **`PT429` = HTTP 429 = a limit, not a fault.** Show its message, do not retry automatically, offer WhatsApp. (Before migration 0009 this arrived
   as HTTP 500 with code `P0429`.)
4. **A token problem (`PGRST301`, HTTP 401) breaks PUBLIC calls too.** PostgREST checks the Authorization header before anything else, so a stale
   staff token sent with `get_availability` or `place_order_request` is rejected. The website should send only the anon key; Stockroom should
   refresh the session and retry once, then ask the person to sign in again.
5. `401` + `42501` = not signed in (or token for the anon role); `403` + `42501` = signed in but not allowed (message says which rank is needed).
6. Unknown order reference and wrong phone number produce the **same** `order not found` response on purpose. Do not try to tell them apart.
7. Replaying a request with the same idempotency key returns the first answer (HTTP 200); it is never an error. Use a new key only for a new user action.
8. Statement timeouts (`57014`) arrive as HTTP 500: treat as "try again shortly", fall back to "Check availability".



## Our own functions (public website calls and staff actions)

| Case | What happened | HTTP | `code` | `message` | `details` | `hint` | What the page should do |
|---|---|---|---|---|---|---|---|
| ST-last-owner | Deactivate / remove the only active owner (service role or direct SQL) | 400 | `P0001` | there must always be one active owner: add another owner first |  |  | Tell the owner to add a second owner first. |
| PO-name | Name or address blank | 400 | `P0001` | name and address are required |  |  | Show the message under the form and keep the bag. |
| PO-phone | Phone is not exactly 10 digits | 400 | `P0001` | phone must be 10 digits |  |  | Show the message under the form and keep the bag. |
| PO-lines-type | Lines is not a list | 400 | `P0001` | lines must be a list |  |  | Programming error in the page; do not show to the customer. |
| PO-lines-0 | No lines | 400 | `P0001` | between 1 and 40 lines allowed |  |  | The bag is empty. |
| PO-lines-41 | 41 lines | 400 | `P0001` | between 1 and 40 lines allowed |  |  | Too many different items in one order request. |
| PO-ref-format | Order reference is not W<DDMM>-XXXX-XX | 400 | `P0001` | bad order reference |  |  | Programming error; regenerate the reference and retry once. |
| PO-ref-check | Check digits do not match the items sent (or lines in another order) | 400 | `P0001` | order reference check digits do not match the items |  |  | Regenerate the reference from the bag and retry once. |
| PO-qty-0 | Quantity 0 | 400 | `P0001` | quantity must be 1 to 99 |  |  | Show the message under the form and keep the bag. |
| PO-qty-100 | Quantity 100 | 400 | `P0001` | quantity must be 1 to 99 |  |  | Show the message under the form and keep the bag. |
| PO-unknown | Product or size not on the website (or unpublished) | 400 | `P0001` | item not available on the website: no-such-product M |  |  | Remove the item from the bag and say it is no longer listed. |
| PO-unpublished | Unpublished product | 400 | `P0001` | item not available on the website: tst-hidden M |  |  | Same as PO-unknown (does not reveal that it exists). |
| PO-dup-line | The same product+size twice in one request | 409 | `23505` | duplicate key value violates unique constraint "order_lines_pkey" | Key (order_id, variant_id)=(<uuid>, <uuid>) already exists. |  | Merge the lines in the bag before sending (the bag already does). |
| PO-key-short | Idempotency key shorter than 8 characters | 400 | `P0001` | idempotency key required (min 8 chars) |  |  | Programming error; generate a longer key. |
| PO-ref-used | Same order reference, new idempotency key (a different tap of Send) | 400 | `P0001` | order reference already used |  |  | Regenerate the reference and retry once. |
| PO-key-other-action | Idempotency key already used for a different action | 400 | `P0001` | idempotency key already used for a different action |  |  | Programming error: one key per user action. |
| PO-rate-hour | 6th request in an hour from one phone | 429 | `PT429` | too many order requests from this phone number - please wait a while or message the shop on WhatsApp |  |  | Tell the customer to wait or message the shop on WhatsApp. Do NOT retry automatically. |
| PO-rate-day | 16th request in a day from one phone | 429 | `PT429` | too many order requests from this phone number - please wait a while or message the shop on WhatsApp |  |  | Same as PO-rate-hour. |
| RP-unknown | Unknown reference | 400 | `P0001` | order not found |  |  | 'We could not find this order - check the reference or WhatsApp us.' Same text for a wrong phone. |
| RP-wrong-phone | Right reference, wrong phone (must equal RP-unknown) | 400 | `P0001` | order not found |  |  | Same as RP-unknown. |
| RP-paise-text | claimed_paise is not a number | 400 | `22P02` | invalid input syntax for type integer: "abc" |  |  | Programming error. |
| RP-paise-big | claimed_paise beyond int range | 400 | `22003` | value "99999999999" is out of range for type integer |  |  | Programming error. |
| GA-array | product ids not an array | 400 | `22P02` | malformed array literal: "abc" | Array value must start with "{" or dimension information. |  | Programming error; fall back to 'Check availability'. |
| ST-anon | Anonymous caller (or expired session) reaches a staff function | 401 | `42501` | permission denied for function confirm_and_reserve |  |  | Sign in again. |
| ST-stranger | Signed in but not on the staff list | 403 | `42501` | not allowed: sign in as shop staff |  |  | 'This account is not shop staff.' |
| ST-rank | Staff calls a manager function | 403 | `42501` | not allowed: needs manager access |  |  | 'Needs manager access.' |
| ST-owner | Manager calls the owner summary | 403 | `42501` | not allowed: needs owner access |  |  | 'Owner only.' |
| ST-notfound | Order id does not exist | 400 | `P0001` | order not found |  |  | Refresh the list. |
| ST-no-delivery | Confirm without a delivery charge | 400 | `P0001` | add the delivery charge first |  |  | Ask staff to enter the charge. |
| ST-discount | Discount equal to or above the items total | 400 | `P0001` | discount must be below the items total |  |  | Fix the amount. |
| ST-state | Action not allowed from the current status | 400 | `P0001` | cannot dispatch an order that is request |  |  | Refresh; show the current status. |
| ST-pay-state | Verify payment on a request that was never reserved | 400 | `P0001` | cannot verify_payment an order that is request |  |  | Refresh. |
| ST-pay-amount | Verified amount differs from the agreed bill | 400 | `P0001` | amount 1 differs from the agreed bill 104900 - fix the bill first |  |  | Show the agreed amount. |
| ST-pay-dup-ref | UPI reference already used on another order | 409 | `23505` | duplicate key value violates unique constraint "payments_upi_ref_once" | Key (lower(upi_ref))=(<upi-ref>) already exists. |  | Check the reference. |
| ST-cancel-paid | Cancel a paid order | 400 | `P0001` | cannot cancel an order that is paid |  |  | Use refund instead. |
| ST-short-stock | Not enough free stock to hold | 400 | `P0001` | not enough stock: tst-b-blue size M has 0 free, order needs 1 |  |  | Offer to contact the customer. |
| ST-qty-neg | Receive a negative quantity | 400 | `P0001` | quantity must be positive |  |  | Fix the number. |
| ST-uuid | Order id is not a UUID | 400 | `22P02` | invalid input syntax for type uuid: "not-a-uuid" |  |  | Programming error. |
| ST-barcode | Unknown barcode in a counter sale | 400 | `P0001` | unknown barcode |  |  | 'Barcode not found.' |
| ST-sale-pay | Counter sale payments do not equal the bill | 400 | `P0001` | payments 1 do not equal the bill 149900 |  |  | Show the bill amount. |
| PO-rate-global | More than 300 order requests in the last hour, from anyone | 429 | `PT429` | the shop is receiving a lot of requests right now - please try again shortly |  |  | Show the message; do not retry automatically; offer WhatsApp. |

## PostgREST / gateway-level errors

| Case | What happened | HTTP | `code` | `message` | `details` | `hint` | What the page should do |
|---|---|---|---|---|---|---|---|
| PG-fn-missing | Function or parameter names do not match (also: function hidden from this role) | 404 | `PGRST202` | Could not find the function public.get_availability(wrong) in the schema cache | Searched for the function public.get_availability with parameter wrong or with a single unnamed json/jsonb parameter, but no matches were found in the schema cache. |  | Programming error. |
| PG-json | Request body is not valid JSON | 400 | `PGRST102` | Empty or invalid json |  |  | Programming error. |
| PG-denied-anon | Function refused to anon | 401 | `42501` | permission denied for function pack_order |  |  | Sign in. |
| PG-denied-user | Table refused to a signed-in user | 403 | `42501` | permission denied for table orders |  |  | Never done by the apps. |
| PG-no-table | Table that does not exist | 404 | `42P01` | relation "public.no_such_table" does not exist |  |  | Programming error. |
| PG-method | GET on a function that writes | 405 | `25006` | cannot execute INSERT in a read-only transaction |  |  | Programming error: use POST. |
| PG-accept | Unsupported Accept header | 406 | `PGRST107` | None of these media types are available: application/octet-stream |  |  | Programming error. |
| PG-schema | Schema not exposed | 406 | `PGRST106` | The schema must be one of the following: public |  |  | Programming error. |
| PG-single | Accept single object but several rows | 406 | `PGRST116` | JSON object requested, multiple (or no) rows returned | The result contains 3 rows |  | Programming error. |
| PG-jwt-expired | Token expired (more than 30 s ago) | 401 | `PGRST301` | JWT expired |  |  | Refresh the session or fall back to the anon key; a 401 here also breaks PUBLIC calls. |
| PG-jwt-bad | Token malformed | 401 | `PGRST301` | JWSError (JSONDecodeError "Not valid base64url") |  |  | Same as PG-jwt-expired. |
| PG-jwt-public | Expired token on a PUBLIC call | 401 | `PGRST301` | JWT expired |  |  | A stale staff token in the browser breaks the shop page - send the anon key for public calls. |
| PG-timeout | Statement timeout (anon limit 3 s on hosted projects; forced to 1 ms here) | 500 | `57014` | canceling statement due to statement timeout |  |  | Show 'try again in a moment'; fall back to 'Check availability'. |

## Success responses recorded (for contrast)

`PO-ok` → HTTP 200, `PO-first` → HTTP 200, `RP-ok` → HTTP 200

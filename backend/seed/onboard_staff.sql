-- O4U staff onboarding. Run ONCE per person by the owner, in the Supabase SQL editor (runs as postgres) - never from the website.
-- No real e-mails or ids live in this repository. The three addresses below end in .invalid on purpose: replace them
-- with the e-mails you used when you created each person in Supabase Auth. Until you do, running this file does nothing
-- harmful - it stops with "no sign-in account with that e-mail".
--
-- Order of work (owner):
--   1. Dashboard > Authentication > Users > "Add user" (or invite) for yourself, then for each person. Use a strong
--      password or an invite link, turn on MFA for the owner account.  [Nothing is typed into this repository.]
--   2. Edit the three lines below (e-mail, display name as it should appear in the audit trail), run the file.
--   3. Check:  select user_id, name, role, active from staff;
--
-- Roles:  owner = everything incl. revenue numbers;  manager = discounts, refunds, recounts, money ledger;
--         staff = run orders and stock, no money ledger.
-- Switch a person off:  select deactivate_staff('<their auth user id>');   (history is kept; the last owner cannot be switched off)
-- Change a role: run onboard_staff_by_email again with the new role.

select onboard_staff_by_email('owner-email-goes-here@example.invalid',   'Owner display name',   'owner');
select onboard_staff_by_email('manager-email-goes-here@example.invalid', 'Manager display name', 'manager');
select onboard_staff_by_email('staff-email-goes-here@example.invalid',   'Staff display name',   'staff');

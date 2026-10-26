-- O4U backend, migration 0008: pin the search_path of the three helper functions that had none. Idempotent. Changes no data and no behaviour.
-- Found by Supabase's Security Advisor on the hosted dev project ("Function Search Path Mutable": setting, forbid_change, keep_one_owner).
-- Every other function already pins its search_path in its definition. A function without one resolves names through the caller's
-- search_path, which is the classic way a hostile schema shadows a table or function.
alter function public.setting(text)   set search_path = public;
alter function public.forbid_change() set search_path = public;
alter function public.keep_one_owner() set search_path = public;

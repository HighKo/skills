BEGIN;
DO $$ BEGIN
  IF current_database() <> 'chaanz_booking_local' THEN
    RAISE EXCEPTION 'Fixtures may only run in chaanz_booking_local';
  END IF;
END $$;

-- Copy the development user's known password hash; preserve real auth flows.
INSERT INTO auth.portal_auth_user
SELECT (jsonb_populate_record(NULL::auth.portal_auth_user, to_jsonb(u) || jsonb_build_object(
  'id', '71000000-0000-4000-8000-000000000001',
  'user_id', '72000000-0000-4000-8000-000000000001',
  'email', 'manager@booking.test', 'roles', jsonb_build_array('manager', 'editor'),
  'created_at', now(), 'updated_at', now()))).*
FROM auth.portal_auth_user u WHERE email = 'devorganizer1@chaanz.com'
ON CONFLICT DO NOTHING;
INSERT INTO auth.portal_auth_user
SELECT (jsonb_populate_record(NULL::auth.portal_auth_user, to_jsonb(u) || jsonb_build_object(
  'id', '71000000-0000-4000-8000-000000000002',
  'user_id', '72000000-0000-4000-8000-000000000002',
  'email', 'editor@booking.test', 'roles', jsonb_build_array('editor'),
  'created_at', now(), 'updated_at', now()))).*
FROM auth.portal_auth_user u WHERE email = 'devorganizer1@chaanz.com'
ON CONFLICT DO NOTHING;
INSERT INTO platform.account (id,name,email,auth_user_id,created_at,updated_at)
VALUES ('72000000-0000-4000-8000-000000000001','Booking Manager','manager@booking.test','71000000-0000-4000-8000-000000000001',now(),now()),
       ('72000000-0000-4000-8000-000000000002','Booking Editor','editor@booking.test','71000000-0000-4000-8000-000000000002',now(),now())
ON CONFLICT DO NOTHING;
INSERT INTO platform.account_organizer_link (account_id,organizer_id,created_at)
SELECT id, 'd35822fa-0410-41b7-b25e-3ce01f4067b9'::uuid, now()
FROM platform.account WHERE email IN ('manager@booking.test','editor@booking.test')
ON CONFLICT DO NOTHING;

-- Keep Highfield's established platform ID so the branded app opens our fixture.
CREATE TEMP TABLE selected_event AS
SELECT id FROM platform.event WHERE platform_id='1060bf06-ac59-4ad1-b59e-28473b64b369'
ORDER BY start_time DESC, id LIMIT 1;
UPDATE platform.event SET archived_at=now(),updated_at=now()
WHERE platform_id='1060bf06-ac59-4ad1-b59e-28473b64b369' AND id NOT IN (SELECT id FROM selected_event);
-- Explicitly opt this isolated synthetic event into the booking preview.
UPDATE platform.event SET features=features | 65536,name='{"all":"Booking Local"}',start_time=current_date,
  end_time=current_date + interval '30 days',published_at=now()-interval '1 day',
  announcement_published_at=now()-interval '1 day',archived_at=NULL,updated_at=now(),match_making_configuration_id=NULL
WHERE id IN (SELECT id FROM selected_event);

INSERT INTO platform.session
SELECT (jsonb_populate_record(NULL::platform.session, to_jsonb(s) || jsonb_build_object(
  'id', f.id, 'external_id', NULL, 'name', jsonb_build_object('all', f.title),
  'description', jsonb_build_object('en', 'A synthetic workshop for testing the complete session booking flow. Apply with your name, company and role. Decisions are made in the local portal; all emails stay in the local inbox.'),
  'start_date', current_date + interval '1 day 10 hours' + f.slot * interval '1 hour',
  'end_date', current_date + interval '1 day 10 hours 45 minutes' + f.slot * interval '1 hour',
  'published_at', now()-interval '1 day', 'archived_at', NULL, 'import_deleted_at', NULL,
  'created_at', now(), 'updated_at', now(), 'booking_enabled',false,'booking_capacity',NULL,
  'is_time_set',true,'highlighted',true))).*
FROM (SELECT * FROM platform.session WHERE event_id IN (SELECT id FROM selected_event) ORDER BY id LIMIT 1) s
CROSS JOIN (VALUES
  ('73000000-0000-4000-8000-000000000001','01 · Booking round trip',0),
  ('73000000-0000-4000-8000-000000000002','02 · Capacity and rejection',1),
  ('73000000-0000-4000-8000-000000000003','03 · Closed intake',2),
  ('73000000-0000-4000-8000-000000000004','04 · Ordinary session',3),
  ('73000000-0000-4000-8000-000000000005','05 · Automated checks',4)
) AS f(id,title,slot)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.booking_local_setup (version integer PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO public.booking_local_setup(version) VALUES (1) ON CONFLICT DO NOTHING;
COMMIT;

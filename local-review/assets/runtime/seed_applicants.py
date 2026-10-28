#!/usr/bin/env python3
"""Add repeatable, synthetic layout fixtures to one local booking session."""
import argparse
from collections import Counter
import json
import uuid

import booking

NAMES = [
    'Alex Morgan', 'Maya Hernández', 'Lukas Schneider', 'Aisha Khan',
    'Zoë Dubois', 'Søren Nielsen', '王伟', 'Fatima Al-Zahra',
    'Chloé Martin', 'Oskar Kowalski', 'Priya Nair', 'Noah Williams',
    'Élodie Lefèvre', 'محمد حسن', 'Yuki Tanaka', 'Amelia O’Connor',
    'Nina Petrović', 'Gabriel Santos', 'Sofia Papadopoulos', 'Emre Yılmaz',
    'Anna-Lena Müller', 'Kwame Mensah', 'Olivia van der Meer', 'David Cohen',
    'Sakura Watanabe', 'Isabella Rossi', 'Mateo García', 'Lin Chen',
    'Charlotte Alexandra von Hohenberg-Schönhausen', 'Sam Taylor',
    'Leila Haddad', 'Felix Weber', 'Camille Bernard', 'Arjun Patel',
    'Freja Andersen', 'Lucas Silva', 'Mei Zhang', 'Nora Ahmed',
    'Ethan Brown', 'Inès Moreau', 'Jasper de Vries', 'Ananya Sharma',
    'Mila Jovanović', 'Sebastian Fischer', 'Lara Costa', 'Daniel Kim',
    'Amara Okafor', 'Hugo Laurent', 'Elena Popescu', 'Leo Andersson',
    'Chiara Bianchi', 'Rafael Oliveira', 'Hannah Schmidt', 'Oliver Smith',
    'Zainab Ali', 'Theo Janssen', 'Clara Fernández', 'Min-jun Park',
    'Victoria Elizabeth Montgomery-Worthington', 'Robin Lee',
]
COMPANIES = [
    'Northstar Events', 'Studio Süd', '', 'Independent',
    'International Association for Sustainable Festivals and Live Experiences',
    'Müller & Partner GmbH', 'Bright Field Productions', 'Kulturwerk Berlin',
    'Small Stage', 'Collective for Arts, Music & Community Engagement',
]
POSITIONS = [
    'Producer', 'Head of Event Operations', '', 'Volunteer',
    'Senior Director of International Partnerships and Audience Development',
    'Student', 'Technical Production Manager', 'Accessibility Coordinator',
    'Co-founder & Creative Director', 'Artist Liaison',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, type=uuid.UUID)
    parser.add_argument('--count', type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.count <= 500:
        parser.error('count must be between 1 and 500')
    if booking.DATABASE != 'chaanz_booking_local':
        raise RuntimeError('This fixture helper is restricted to chaanz_booking_local')
    rows = []
    for index in range(args.count):
        # Preserve the session's existing accepted count and capacity. The new
        # applicants cover pending, rejected and withdrawn table states.
        status = 'pending' if index % 10 < 7 else 'rejected' if index % 10 < 9 else 'withdrawn'
        stable = f'booking-layout-v1:{args.session}:{index}'
        rows.append({
            'id': str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ':application')),
            'attempt_id': str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ':attempt')),
            'user_id': str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ':user')),
            'email': f'layout-{index + 1:03d}@booking.test',
            'name': NAMES[index % len(NAMES)],
            'company': COMPANIES[index % len(COMPANIES)],
            'position': POSITIONS[(index * 3) % len(POSITIONS)],
            'status': status, 'ordinal': index + 1,
        })
    payload = json.dumps(rows, ensure_ascii=False).replace("'", "''")
    query = f"""
BEGIN;
DO $$ BEGIN
  IF current_database() <> 'chaanz_booking_local' THEN
    RAISE EXCEPTION 'Local layout fixtures only';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM platform.session WHERE id='{args.session}' AND booking_enabled) THEN
    RAISE EXCEPTION 'Choose an existing session with booking enabled';
  END IF;
END $$;
SELECT id FROM platform.session WHERE id='{args.session}' FOR UPDATE;
CREATE TEMP TABLE layout_rows AS SELECT * FROM jsonb_to_recordset('{payload}'::jsonb)
AS x(id uuid, attempt_id uuid, user_id uuid, email text, name text, company text, position text, status text, ordinal int);
INSERT INTO platform.booking_application(id, session_id, user_id, current_attempt_id)
SELECT id, '{args.session}', user_id, attempt_id FROM layout_rows ON CONFLICT DO NOTHING;
INSERT INTO platform.booking_attempt(id, application_id, email, name, company, position, status, decision, submitted_at, decided_at, withdrawn_at)
SELECT attempt_id, id, email, name, company, position, status,
  CASE WHEN status='rejected' THEN 'rejected' ELSE '' END,
  now() - ordinal * interval '37 minutes',
  CASE WHEN status='rejected' THEN now() - interval '17 minutes' ELSE NULL END,
  CASE WHEN status='withdrawn' THEN now() - interval '9 minutes' ELSE NULL END
FROM layout_rows ON CONFLICT DO NOTHING;
COMMIT;
SELECT json_build_object('session', s.name, 'capacity', s.booking_capacity,
  'applications', (SELECT count(*) FROM platform.booking_application WHERE session_id=s.id))
FROM platform.session s WHERE s.id='{args.session}';
"""
    result = booking.sql(query)
    print(result.splitlines()[-1])
    print('Synthetic fixture set:', dict(Counter(row['status'] for row in rows)))
    print('Existing records and settings retained. Rerunning does not duplicate fixtures. No emails queued.')


if __name__ == '__main__':
    main()


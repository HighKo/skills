#!/usr/bin/env python3
"""Exercise real local auth and booking APIs; no external mail or mocked booking state."""
import argparse
import base64
import csv
import io
import http.client
import json
import re
import time
import urllib.error
import urllib.request
import uuid
import booking

BASE = 'http://127.0.0.1:8082'
PLATFORM = '1060bf06-ac59-4ad1-b59e-28473b64b369'
ORGANIZER = 'd35822fa-0410-41b7-b25e-3ce01f4067b9'
CHECKS = []


def request(method, path, body=None, token=None, expected=200, chunked=False):
    headers = {'Content-Type': 'application/json', 'Accept-Language': 'en'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if chunked:
        conn = http.client.HTTPConnection('127.0.0.1', 8082, timeout=45)
        try:
            payload = json.dumps(body).encode()
            conn.request(method, path, body=iter([payload[:10], payload[10:]]), headers=headers, encode_chunked=True)
            response = conn.getresponse()
            data = response.read()
            assert response.status == expected, (response.status, data[:500])
            return json.loads(data)
        finally:
            conn.close()
    req = urllib.request.Request(BASE + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            code, data = response.status, response.read()
    except urllib.error.HTTPError as error:
        code, data = error.code, error.read()
    assert code == expected, (method, path, code, data.decode()[:500])
    try:
        return json.loads(data)
    except ValueError:
        return data.decode()


def messages():
    with urllib.request.urlopen('http://127.0.0.1:8090/messages', timeout=5) as response:
        return json.load(response)


def latest_code(email):
    for message in reversed(messages()):
        if message['to'] == email and not message['subject'].startswith('Session booking:'):
            match = re.search(r'(?<!\d)(\d{3})[- ]?(\d{3})(?!\d)', message['bodyText'])
            if match:
                return match[1] + match[2]
    raise RuntimeError('No captured OTP for ' + email)


def portal_login(email):
    request('POST', '/auth/v2/portal/otp', {'username': email, 'password': booking.required_local_setting('CHAANZ_LOCAL_PORTAL_PASSWORD')})
    return request('POST', '/auth/v3/portal/token', {'username': email, 'otp': latest_code(email)})['accessToken']


def app_login(email):
    path = f'/auth/v2/platforms/{PLATFORM}'
    request('POST', path + '/otp', {'username': email})
    token = request('POST', path + '/token', {'username': email, 'password': latest_code(email)})['accessToken']
    claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
    return token, claims['sub']


def passed(name):
    CHECKS.append(name)
    print('PASS: ' + name, flush=True)


def main(configure_manual=False):
    booking.verify_pins()
    event, series = booking.sql("SELECT id,event_series_id FROM platform.event WHERE name->>'all'='Booking Local'").split('|')
    manager = portal_login('manager@booking.test')
    editor = portal_login('editor@booking.test')
    passed('Manager and editor sign in through real OTP email capture')
    session = str(uuid.uuid4())
    # Dedicated synthetic session for each run: manual scenario data is left intact.
    booking.sql(f"""INSERT INTO platform.session SELECT
      (jsonb_populate_record(NULL::platform.session, to_jsonb(s) || jsonb_build_object(
       'id','{session}','name',jsonb_build_object('all','Verification {session[:8]}'),
       'booking_enabled',false,'booking_capacity',NULL))).*
      FROM platform.session s WHERE id='73000000-0000-4000-8000-000000000005'""")
    portal = f'/portal/organizers/{ORGANIZER}/platforms/{PLATFORM}/events/{event}/sessions/{session}/booking'
    request('GET', portal, token=editor, expected=403)
    request('PUT', portal, {'enabled': True, 'capacity': 1}, manager)
    passed('Editor denied; manager configures capacity')
    token_a, user_a = app_login(f'alex-{session[:8]}@booking.test')
    token_b, user_b = app_login(f'blair-{session[:8]}@booking.test')
    app_a = f'/app/1.44.1/platforms/{PLATFORM}/users/{user_a}/events/{event}/sessions/{session}/booking'
    app_b = f'/app/1.44.1/platforms/{PLATFORM}/users/{user_b}/events/{event}/sessions/{session}/booking'
    assert request('GET', app_a, token=token_a)['application'] is None
    passed('Shared login alone does not create an application')
    form = {'name': 'Alex Morgan', 'company': 'Northstar Events', 'position': 'Event Operations'}
    a = request('POST', app_a, form, token_a, chunked=True)['application']
    b = request('POST', app_b, {**form, 'name': 'Blair Chen'}, token_b)['application']
    assert a['status'] == b['status'] == 'pending'
    assert request('POST', app_a, form, token_a)['application']['attemptID'] == a['attemptID']
    targets = lambda item: {key: item[key] for key in ('applicationID', 'attemptID')}
    decision = request('POST', portal + '/decisions', {'decision': 'accepted', 'applications': [targets(a), targets(b)]}, manager)
    assert decision['results'][0]['application']['status'] == 'accepted'
    assert decision['results'][1]['error'] == 'capacity_exceeded'
    assert request('GET', app_a, token=token_a)['application']['status'] == 'accepted'
    passed('Apply through chunked HTTP, duplicate-submit safety, ordered acceptance and final-seat capacity')
    export = list(csv.DictReader(io.StringIO(request('GET', portal + '/participants.csv', token=manager))))
    assert len(export) == 1 and export[0]['name'] == form['name']
    assert export[0]['status'] == 'accepted'
    assert export[0]['applicationID'] == a['applicationID'] and export[0]['attemptID'] == a['attemptID']
    assert export[0]['submittedAt'] and export[0]['decidedAt'] and not export[0]['withdrawnAt']
    request('GET', portal + '/applications.csv', token=editor, expected=403)
    applications = list(csv.DictReader(io.StringIO(request('GET', portal + '/applications.csv', token=manager))))
    assert len(applications) == 2 and {row['status'] for row in applications} == {'accepted', 'pending'}
    passed('Participant and all-application CSVs include current attempts, status, timestamps and IDs; editor export denied')
    request('POST', app_a + '/withdraw', targets(a), token_a)
    assert request('GET', portal, token=manager)['accepted'] == 0
    a2 = request('POST', app_a + '/reapply', {**targets(a), **form}, token_a)['application']
    assert a2['attemptID'] != a['attemptID'] and a2['applicationID'] == a['applicationID']
    assert a2['status'] == 'pending'
    stale = request('POST', portal + '/decisions', {'decision': 'accepted', 'applications': [targets(a)]}, manager)
    assert stale['results'][0]['error'] == 'stale_attempt'
    passed('Withdrawal releases a seat; reapplication has a new attempt; stale decisions rejected')
    request('POST', portal + '/decisions', {'decision': 'rejected', 'applications': [targets(b)]}, manager)
    assert request('GET', app_b, token=token_b)['application']['status'] == 'rejected'
    request('POST', app_b + '/withdraw', targets(b), token_b, expected=409)
    passed('Rejection reaches applicant and cannot be withdrawn/restarted')
    request('PUT', portal, {'enabled': False}, manager)
    assert request('GET', app_a, token=token_a)['application']['status'] == 'pending'
    request('POST', app_a + '/withdraw', targets(a2), token_a)
    request('POST', app_a + '/reapply', {**targets(a2), **form}, token_a, expected=409)
    passed('Closed intake preserves status and withdrawal but rejects reapplication')
    current = list(csv.DictReader(io.StringIO(request('GET', portal + '/applications.csv', token=manager))))
    assert len(current) == 2 and {row['status'] for row in current} == {'withdrawn', 'rejected'}
    assert {row['attemptID'] for row in current} == {a2['attemptID'], b['attemptID']}
    assert next(row for row in current if row['status'] == 'withdrawn')['withdrawnAt']
    assert next(row for row in current if row['status'] == 'rejected')['decidedAt']
    assert list(csv.DictReader(io.StringIO(request('GET', portal + '/participants.csv', token=manager)))) == []
    passed('All-applications CSV reflects final current attempts without historical duplicates; participants export excludes withdrawn/rejected')
    for _ in range(30):
        captured = [m for m in messages() if m['to'] in (f'alex-{session[:8]}@booking.test', f'blair-{session[:8]}@booking.test') and m['subject'].startswith('Session booking:')]
        if len(captured) >= 2:
            break
        time.sleep(1)
    assert len(captured) == 2
    assert {m['subject'] for m in captured} == {'Session booking: accepted', 'Session booking: rejected'}
    assert all('Verification ' + session[:8] in m['bodyText'] for m in captured)
    passed('Durable acceptance/rejection emails captured with the correct session')
    public = request('GET', f'/app/1.44.1/platforms/{PLATFORM}/events')
    def find_session(value, wanted):
        if isinstance(value, dict):
            if value.get('id') == wanted and 'bookingConfigured' in value:
                return value
            for child in value.values():
                found = find_session(child, wanted)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find_session(child, wanted)
                if found:
                    return found
    ordinary = find_session(public, '73000000-0000-4000-8000-000000000004')
    closed = find_session(public, session)
    assert ordinary and ordinary['bookingConfigured'] is False
    assert closed and closed['bookingConfigured'] is True and closed['bookingEnabled'] is False
    passed('Public feed distinguishes ordinary sessions and closed configured sessions')
    # Preserve the reviewer's manual session settings unless explicitly requested.
    if configure_manual:
        for number, capacity in ((1, 2), (2, 1), (3, 2)):
            target = portal.replace(session, f'73000000-0000-4000-8000-{number:012d}')
            request('PUT', target, {'enabled': True, 'capacity': capacity}, manager)
    manual_url = f'http://localhost:3000/en/dashboard/apps/{PLATFORM}/event-series/{series}/events/{event}/sessions/73000000-0000-4000-8000-000000000001'
    booking.save(booking.ROOT / 'verification.json', {'at': time.time(), 'checks': CHECKS, 'testSession': session,
        'event': event, 'eventSeries': series, 'manualSessionURL': manual_url,
        'revisions': booking.read_json(booking.ROOT / 'revisions.json'),
        'limitations': ['API verification; browser and Android UI walkthrough not automated in this session.']})
    print('Manual session: ' + manual_url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-manual', action='store_true', help='Explicitly reopen/reconfigure the three manual scenario sessions; existing applicants remain')
    main(configure_manual=parser.parse_args().configure_manual)

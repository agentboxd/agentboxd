// Meetings (calendar): the SDK's calendar namespace and the CLI's `events` commands (run `npm run build` first).
// fetch is a fake that records each call. No dependencies: node:test.
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { Agentboxd, AgentboxdError } from 'agentboxd';
import { run } from '../dist/esm/cli/run.js';

const EVENT_ID = '9d7b5f3e-1c0a-4e8d-b6f4-2a0c8e6d4b13';

const event = (over = {}) => ({
  id: EVENT_ID,
  inbox_id: 'inb_1',
  uid: 'abc@google.com',
  recurrence_id: null,
  sequence: 0,
  role: 'attendee',
  status: 'confirmed',
  response: 'needs_action',
  responded_at: null,
  reply_expected: true,
  title: 'Onboarding plan sync',
  description: 'Agenda in the shared doc.',
  location: null,
  url: null,
  conference: { provider: 'google_meet', url: 'https://meet.google.com/abc-defg-hij' },
  start: '2026-11-10T15:00:00.000Z',
  end: '2026-11-10T15:30:00.000Z',
  all_day: false,
  time_zone: null,
  floating: false,
  recurrence: null,
  organizer: { email: 'alex@example.com', name: 'Alex Example' },
  organizer_verified: true,
  attendees: [
    { email: 'alex@example.com', name: 'Alex Example', role: 'req_participant', partstat: 'accepted', rsvp: true },
    { email: 'bot@homingbox.net', name: null, role: 'req_participant', partstat: 'needs_action', rsvp: true },
  ],
  proposals: [],
  source: 'invite',
  message_id: 'msg_1',
  screening: { state: 'screened', reason: null, released_at: null },
  created_at: '2026-11-04T10:00:00.000Z',
  updated_at: '2026-11-04T10:00:00.000Z',
  ...over,
});
const sent = { id: 'msg_out', direction: 'outbound', status: 'queued', to: ['alex@example.com'] };

/** Routes: { 'METHOD /path': body | (url, init) => [status, body] }. Unmatched → 404. `path` is the raw (encoded) path. */
function fakeApi(routes = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    const key = `${init.method ?? 'GET'} ${u.pathname}`;
    calls.push({ key, url: u, init, body: init.body ? JSON.parse(init.body) : undefined });
    const r = routes[key];
    const [status, body] = r === undefined ? [404, { error: { code: 'not_found', message: 'Not found' } }] : typeof r === 'function' ? r(u, init) : [200, r];
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  };
  return { calls, fetch };
}

const client = (routes) => {
  const api = fakeApi(routes);
  return { mr: new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch: api.fetch }), calls: api.calls };
};

test('calendar.list and listAll pass the filters; Dates become ISO times', async () => {
  const page = { data: [event()], next_cursor: null };
  const { mr, calls } = client({ 'GET /v1/inboxes/inb_1/calendar/events': page, 'GET /v1/calendar/events': page });
  const r = await mr.calendar.list('inb_1', {
    from: new Date('2026-11-01T00:00:00Z'),
    to: '2026-12-01T00:00:00Z',
    role: 'attendee',
    response: 'needs_action',
    status: 'confirmed',
    limit: 10,
  });
  assert.equal(r.data[0].id, EVENT_ID);
  assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), {
    from: '2026-11-01T00:00:00.000Z',
    to: '2026-12-01T00:00:00Z',
    role: 'attendee',
    response: 'needs_action',
    status: 'confirmed',
    limit: '10',
  });
  await mr.calendar.listAll({ message_id: 'msg_1', include_unscreened: true });
  assert.equal(calls[1].key, 'GET /v1/calendar/events');
  assert.deepEqual(Object.fromEntries(calls[1].url.searchParams), { message_id: 'msg_1', include_unscreened: 'true' });
});

test('calendar.get, with the screening opt-ins as query parameters', async () => {
  const { mr, calls } = client({ [`GET /v1/calendar/events/${EVENT_ID}`]: event() });
  assert.equal((await mr.calendar.get(EVENT_ID)).title, 'Onboarding plan sync');
  await mr.calendar.get(EVENT_ID, { include_held: true });
  assert.equal(calls[1].url.search, '?include_held=true');
});

test('calendar.respond posts the answer (propose Dates as ISO) with the idempotency key', async () => {
  const { mr, calls } = client({ [`POST /v1/calendar/events/${EVENT_ID}/respond`]: () => [202, { event: event({ response: 'tentative' }), message: sent }] });
  const r = await mr.calendar.respond(EVENT_ID, { response: 'accepted', comment: 'See you there' }, { idempotencyKey: 'k1' });
  assert.equal(r.message.id, 'msg_out');
  assert.deepEqual(calls[0].body, { response: 'accepted', comment: 'See you there' });
  assert.equal(calls[0].init.headers['Idempotency-Key'], 'k1');
  assert.equal(calls[0].url.search, '');
  await mr.calendar.respond(EVENT_ID, { response: 'tentative', propose: { start: new Date('2026-11-11T09:00:00Z'), end: '2026-11-11T09:30:00Z' } });
  assert.deepEqual(calls[1].body, { response: 'tentative', propose: { start: '2026-11-11T09:00:00.000Z', end: '2026-11-11T09:30:00Z' } });
  assert.equal(calls[1].init.headers['Idempotency-Key'], undefined);
});

test('calendar.respond surfaces 409 message_withheld for a held invite', async () => {
  const { mr } = client({ [`POST /v1/calendar/events/${EVENT_ID}/respond`]: () => [409, { error: { code: 'message_withheld', message: 'held' } }] });
  await assert.rejects(mr.calendar.respond(EVENT_ID, { response: 'accepted' }), (e) => e instanceof AgentboxdError && e.status === 409 && e.code === 'message_withheld');
});

test('calendar.create, update and cancel', async () => {
  const own = event({ role: 'organizer', response: null, source: 'agent', message_id: null, screening: null });
  const { mr, calls } = client({
    'POST /v1/inboxes/inb_1/calendar/events': () => [201, { event: own, message: sent }],
    [`PATCH /v1/calendar/events/${EVENT_ID}`]: { event: own, message: sent },
    [`POST /v1/calendar/events/${EVENT_ID}/cancel`]: { event: { ...own, status: 'cancelled' }, message: null },
  });
  const created = await mr.calendar.create(
    'inb_1',
    { title: 'Kickoff', start: new Date('2026-11-12T14:00:00Z'), duration_minutes: 45, time_zone: 'Europe/Paris', attendees: [{ email: 'dana@example.com', name: 'Dana' }] },
    { idempotencyKey: 'create-1' },
  );
  assert.equal(created.event.role, 'organizer');
  assert.deepEqual(calls[0].body, {
    title: 'Kickoff',
    start: '2026-11-12T14:00:00.000Z',
    duration_minutes: 45,
    time_zone: 'Europe/Paris',
    attendees: [{ email: 'dana@example.com', name: 'Dana' }],
  });
  assert.equal(calls[0].init.headers['Idempotency-Key'], 'create-1');

  await mr.calendar.update(EVENT_ID, { start: '2026-11-12T15:00:00Z', location: null, message: 'Moved by an hour' });
  assert.equal(calls[1].init.method, 'PATCH');
  assert.deepEqual(calls[1].body, { start: '2026-11-12T15:00:00Z', location: null, message: 'Moved by an hour' });

  const cancelled = await mr.calendar.cancel(EVENT_ID, { message: 'Sorry' });
  assert.equal(cancelled.event.status, 'cancelled');
  assert.equal(cancelled.message, null);
  assert.deepEqual(calls[2].body, { message: 'Sorry' });
});

test('calendar.list with expand: occurrences sends expand=occurrences and returns truncated and series_id', async () => {
  const series = { recurrence: { rrule: 'FREQ=WEEKLY;COUNT=60', rdates: [], exdates: [] } };
  const page = {
    data: [event({ ...series, start: '2026-11-17T09:00:00.000Z', recurrence_id: '2026-11-17T09:00:00.000Z', series_id: EVENT_ID }), event({ id: 'evt_single', series_id: null })],
    next_cursor: null,
    truncated: true,
  };
  const { mr, calls } = client({ 'GET /v1/inboxes/inb_1/calendar/events': page });
  const r = await mr.calendar.list('inb_1', { expand: 'occurrences', from: new Date('2026-11-01T00:00:00Z') });
  assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), { expand: 'occurrences', from: '2026-11-01T00:00:00.000Z' });
  assert.equal(r.truncated, true);
  assert.equal(r.data[0].series_id, EVENT_ID);
  assert.equal(r.data[1].series_id, null);
});

test('draft: true on the four calls that send: the body carries it, the result is the draft (201)', async () => {
  const meetingDraft = (action, method) => ({ id: `drf_${action}`, inbox_id: 'inb_1', status: 'draft', calendar: { action, method, event_id: EVENT_ID, removed_attendees: [] } });
  const { mr, calls } = client({
    [`POST /v1/calendar/events/${EVENT_ID}/respond`]: () => [201, { event: event(), message: null, draft: meetingDraft('respond', 'REPLY') }],
    'POST /v1/inboxes/inb_1/calendar/events': () => [201, { event: null, message: null, draft: meetingDraft('create', 'REQUEST') }],
    [`PATCH /v1/calendar/events/${EVENT_ID}`]: () => [201, { event: event({ role: 'organizer' }), message: null, draft: { ...meetingDraft('update', 'REQUEST'), calendar: { ...meetingDraft('update', 'REQUEST').calendar, removed_attendees: ['sam@example.com'] } } }],
    [`POST /v1/calendar/events/${EVENT_ID}/cancel`]: () => [201, { event: event({ role: 'organizer' }), message: null, draft: meetingDraft('cancel', 'CANCEL') }],
  });
  const answered = await mr.calendar.respond(EVENT_ID, { response: 'accepted', draft: true });
  assert.deepEqual(calls[0].body, { response: 'accepted', draft: true });
  assert.equal(answered.message, null);
  assert.equal(answered.draft.calendar.action, 'respond');

  const created = await mr.calendar.create('inb_1', { title: 'Kickoff', start: '2026-11-12T14:00:00Z', attendees: [{ email: 'dana@example.com' }], draft: true });
  assert.equal(calls[1].body.draft, true);
  assert.equal(created.event, null);
  assert.equal(created.draft.calendar.event_id, EVENT_ID);

  const changed = await mr.calendar.update(EVENT_ID, { attendees: [{ email: 'dana@example.com' }], draft: true });
  assert.deepEqual(calls[2].body, { attendees: [{ email: 'dana@example.com' }], draft: true });
  assert.deepEqual(changed.draft.calendar.removed_attendees, ['sam@example.com']);

  const cancelled = await mr.calendar.cancel(EVENT_ID, { draft: true });
  assert.deepEqual(calls[3].body, { draft: true });
  assert.equal(cancelled.draft.calendar.method, 'CANCEL');
});

test('event and inbox ids are path segments: encoded, and dot segments refused before any call', async () => {
  const { mr, calls } = client({});
  await assert.rejects(mr.calendar.get('a/b'), (e) => e instanceof AgentboxdError && e.status === 404);
  assert.equal(calls[0].url.pathname, '/v1/calendar/events/a%2Fb');
  await assert.rejects(mr.calendar.list('x?y'), (e) => e.status === 404);
  assert.equal(calls[1].url.pathname, '/v1/inboxes/x%3Fy/calendar/events');
  for (const bad of ['..', '.']) {
    await assert.rejects(mr.calendar.respond(bad, { response: 'accepted' }), (e) => e instanceof AgentboxdError && e.code === 'invalid_argument');
    await assert.rejects(mr.calendar.cancel(bad), (e) => e.code === 'invalid_argument');
    await assert.rejects(mr.calendar.update(bad, { title: 'x' }), (e) => e.code === 'invalid_argument');
  }
  assert.equal(calls.length, 2);
  // A percent-encoded dot segment is encoded again, so it stays one literal segment.
  await assert.rejects(mr.calendar.get('%2e%2e'), (e) => e.status === 404);
  assert.equal(calls[2].url.pathname, '/v1/calendar/events/%252e%252e');
});

// ---------- CLI ----------

const dirs = [];
after(() => dirs.forEach((d) => rmSync(d, { recursive: true, force: true })));

async function cli(argv, routes = {}) {
  const api = fakeApi(routes);
  const dir = mkdtempSync(path.join(tmpdir(), 'abx-cal-'));
  dirs.push(dir);
  let stdout = '';
  let stderr = '';
  const code = await run(argv, {
    stdout: { write: (s) => (stdout += s) },
    stderr: { write: (s) => (stderr += s) },
    env: { AGENTBOXD_API_KEY: 'mr_test_key', AGENTBOXD_BASE_URL: 'http://api.test', AGENTBOXD_CONFIG_DIR: dir },
    readStdin: async () => '',
    stdinIsTTY: true,
    fetch: api.fetch,
    platform: 'linux',
  });
  return { code, stdout, stderr, calls: api.calls };
}

test('CLI events list: table of every inbox or one, filters, unverified organizers flagged', async () => {
  const page = { data: [event(), event({ id: 'evt_2', organizer_verified: false, title: 'Free \u001b[2Jgift' })], next_cursor: 'c2' };
  const all = await cli(['events', 'list', '--response', 'needs_action', '--from', '2026-11-01T00:00:00Z'], { 'GET /v1/calendar/events': page });
  assert.equal(all.code, 0, all.stderr);
  assert.match(all.stdout, /^ID +START \(UTC\) +ROLE +ANSWER +ORGANIZER +TITLE/);
  assert.match(all.stdout, /2026-11-10 15:00 +attendee +needs_action +alex@example.com +Onboarding plan sync/);
  assert.match(all.stdout, /alex@example.com \(unverified\)/);
  assert.ok(!all.stdout.includes('\u001b'), 'an escape sequence in a title is shown as text');
  assert.match(all.stdout, /Free \\u001b\[2Jgift/);
  assert.match(all.stderr, /--cursor c2/);
  assert.deepEqual(Object.fromEntries(all.calls[0].url.searchParams), { response: 'needs_action', from: '2026-11-01T00:00:00.000Z' });

  const one = await cli(['events', 'list', 'inb_1', '--role', 'organizer', '--json'], { 'GET /v1/inboxes/inb_1/calendar/events': { data: [], next_cursor: null } });
  assert.equal(one.code, 0);
  assert.deepEqual(JSON.parse(one.stdout), { data: [], next_cursor: null });
  assert.equal(one.calls[0].url.search, '?role=organizer');

  const bad = await cli(['events', 'list', '--role', 'guest']);
  assert.equal(bad.code, 2);
  assert.match(bad.stderr, /--role must be attendee, organizer/);
  assert.equal(bad.calls.length, 0);
});

test('CLI events list --expand: each occurrence of a series; a series listed once is marked; truncated is said', async () => {
  const series = { recurrence: { rrule: 'FREQ=WEEKLY;COUNT=60', rdates: [], exdates: [] } };
  const expanded = {
    data: [
      event({ ...series, start: '2026-11-17T09:00:00.000Z', series_id: EVENT_ID }),
      event({ ...series, start: '2026-11-24T09:00:00.000Z', series_id: EVENT_ID }),
    ],
    next_cursor: null,
    truncated: true,
  };
  const r = await cli(['events', 'list', 'inb_1', '--expand', '--until', '2027-01-01T00:00:00Z'], { 'GET /v1/inboxes/inb_1/calendar/events': expanded });
  assert.equal(r.code, 0, r.stderr);
  assert.deepEqual(Object.fromEntries(r.calls[0].url.searchParams), { expand: 'occurrences', to: '2027-01-01T00:00:00.000Z' });
  assert.match(r.stdout, /2026-11-17 09:00 +attendee/);
  assert.match(r.stdout, /2026-11-24 09:00 +attendee/);
  assert.ok(!r.stdout.includes('(series)'), 'occurrences are not marked as a series');
  assert.match(r.stderr, /more occurrences than one list gives/);

  const once = await cli(['events', 'list', 'inb_1'], { 'GET /v1/inboxes/inb_1/calendar/events': { data: [event(series)], next_cursor: null } });
  assert.match(once.stdout, /2026-11-10 15:00 \(series\)/);
  assert.equal(once.calls[0].url.search, '');
});

test('CLI events get: the invite text under the untrusted banner, the organizer check, withheld invites', async () => {
  const r = await cli(['events', 'get', EVENT_ID], { [`GET /v1/calendar/events/${EVENT_ID}`]: event({ organizer_verified: false }) });
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /title: +Onboarding plan sync/);
  assert.match(r.stdout, /organizer: alex@example.com \(Alex Example\) +NOT verified/);
  assert.match(r.stdout, /attendee: +bot@homingbox.net +needs_action/);
  assert.match(r.stdout, /join: +https:\/\/meet.google.com\/abc-defg-hij \(google_meet\)/);
  assert.match(r.stdout, /UNTRUSTED EMAIL CONTENT[^\n]*\nAgenda in the shared doc\./);

  const held = event({ title: '[held: phishing]', description: null, conference: null, withheld: { state: 'held', reason: 'phishing' } });
  const w = await cli(['events', 'get', EVENT_ID], { [`GET /v1/calendar/events/${EVENT_ID}`]: held });
  assert.match(w.stdout, /withheld: +held \(phishing\): .*can't be answered until a person releases it/);
});

test('CLI events respond: the answer, a comment, a proposed time; usage errors exit 2 before any call', async () => {
  const route = { [`POST /v1/calendar/events/${EVENT_ID}/respond`]: () => [202, { event: event({ response: 'accepted' }), message: sent }] };
  const ok = await cli(['events', 'respond', EVENT_ID, '--response', 'accepted', '--comment', 'Works for me', '--idempotency-key', 'r1'], route);
  assert.equal(ok.code, 0, ok.stderr);
  assert.deepEqual(ok.calls[0].body, { response: 'accepted', comment: 'Works for me' });
  assert.equal(ok.calls[0].init.headers['Idempotency-Key'], 'r1');
  assert.match(ok.stdout, /Answered accepted: sent msg_out to the organizer, alex@example.com\./);

  const counter = await cli(['events', 'respond', EVENT_ID, '--response', 'tentative', '--propose-start', '2026-11-11T09:00:00Z', '--propose-end', '2026-11-11T09:30:00Z'], route);
  assert.equal(counter.code, 0, counter.stderr);
  assert.deepEqual(counter.calls[0].body, { response: 'tentative', propose: { start: '2026-11-11T09:00:00.000Z', end: '2026-11-11T09:30:00.000Z' } });
  assert.match(counter.stdout, /Proposed 2026-11-11 09:00 to 2026-11-11 09:30 UTC/);

  for (const argv of [
    ['events', 'respond', EVENT_ID],
    ['events', 'respond', EVENT_ID, '--response', 'maybe'],
    ['events', 'respond', EVENT_ID, '--response', 'accepted', '--propose-start', '2026-11-11T09:00:00Z'],
    ['events', 'respond', EVENT_ID, '--response', 'accepted', '--propose-start', 'tomorrow', '--propose-end', '2026-11-11T09:30:00Z'],
    ['events', 'respond', EVENT_ID, '--response', 'accepted', '--to', 'someone@example.com'],
  ]) {
    const r = await cli(argv, route);
    assert.equal(r.code, 2, argv.join(' '));
    assert.equal(r.calls.length, 0);
  }

  const help = await cli(['--help']);
  assert.match(help.stdout, /Meetings:\n {2}events list/);
});

test('CLI events respond --draft: saved for a person to approve, nothing sent', async () => {
  const draft = { id: 'drf_1', inbox_id: 'inb_1', status: 'draft', calendar: { action: 'respond', method: 'REPLY', event_id: EVENT_ID, removed_attendees: [] } };
  const route = { [`POST /v1/calendar/events/${EVENT_ID}/respond`]: () => [201, { event: event(), message: null, draft }] };
  const r = await cli(['events', 'respond', EVENT_ID, '--response', 'declined', '--draft'], route);
  assert.equal(r.code, 0, r.stderr);
  assert.deepEqual(r.calls[0].body, { response: 'declined', draft: true });
  assert.match(r.stdout, /Answered declined: saved as draft drf_1, nothing was sent\..*agentboxd drafts send inb_1 drf_1/);

  const json = await cli(['events', 'respond', EVENT_ID, '--response', 'declined', '--draft', '--json'], route);
  assert.equal(JSON.parse(json.stdout).draft.id, 'drf_1');
});

// formatMessage (src/format.ts): what an agent reads of a message.
import { describe, expect, it } from 'vitest';
import { formatMessage } from '../src/format.js';
import { makeMessage } from './fake-agentboxd.js';

describe('formatMessage', () => {
  it('says when the API cut the body for a list, even when what is left fits (board #216 item 5)', () => {
    const cut = formatMessage(makeMessage({ body_truncated: true }));
    expect(cut).toMatchObject({ body_truncated: true, body_note: 'The body was cut for this list: call get_message for all of it.' });
    expect(cut.extracted_text).toBe('Your code is 482913');
    for (const whole of [makeMessage({ body_truncated: false }), makeMessage()]) {
      expect(formatMessage(whole)).not.toHaveProperty('body_truncated');
      expect(formatMessage(whole)).not.toHaveProperty('body_note');
    }
  });
});

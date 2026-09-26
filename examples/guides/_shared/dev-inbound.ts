/**
 * Local testing only: hands a raw email to a self-hosted Agentboxd dev server (`POST /dev/inbound`,
 * mounted when NODE_ENV=development and INBOUND_PROVIDER=dev). The hosted API at api.agentboxd.com
 * has no such route; there, mail arrives over SMTP like any other email.
 */
export interface DevEmail {
  from: string;
  to: string;
  subject: string;
  text: string;
  /** Message-ID of the email this one replies to (threads it). */
  inReplyTo?: string;
}

export async function deliverLocally(baseUrl: string, mail: DevEmail): Promise<void> {
  const id = `<${Date.now()}.${Math.random().toString(36).slice(2)}@example.test>`;
  const headers = [
    `From: ${mail.from}`,
    `To: ${mail.to}`,
    `Subject: ${mail.subject}`,
    `Message-ID: ${id}`,
    `Date: ${new Date().toUTCString()}`,
    ...(mail.inReplyTo ? [`In-Reply-To: ${mail.inReplyTo}`, `References: ${mail.inReplyTo}`] : []),
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
  ];
  const res = await fetch(`${baseUrl.replace(/\/+$/, '')}/dev/inbound`, {
    method: 'POST',
    headers: { 'Content-Type': 'message/rfc822' },
    body: `${headers.join('\r\n')}\r\n\r\n${mail.text.replace(/\n/g, '\r\n')}\r\n`,
  });
  if (!res.ok) throw new Error(`/dev/inbound answered ${res.status}: ${await res.text()}`);
}

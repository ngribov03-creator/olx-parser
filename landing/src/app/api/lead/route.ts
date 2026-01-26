import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const webhookUrl = process.env.LEAD_WEBHOOK_URL;

  if (!webhookUrl) {
    return NextResponse.json(
      { error: 'Webhook URL is not configured' },
      { status: 500 }
    );
  }

  const payload = await request.json();
  const { name, phone, comment } = payload as {
    name?: string;
    phone?: string;
    comment?: string;
  };

  if (!name || !phone) {
    return NextResponse.json(
      { error: 'Missing required fields' },
      { status: 400 }
    );
  }

  const response = await fetch(webhookUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      name,
      phone,
      comment: comment ?? '',
      source: 'directsell-landing',
      submittedAt: new Date().toISOString(),
      userAgent: request.headers.get('user-agent') ?? 'unknown'
    })
  });

  if (!response.ok) {
    return NextResponse.json(
      { error: 'Webhook request failed' },
      { status: 502 }
    );
  }

  return NextResponse.json({ ok: true });
}

# DirectSell Landing (Next.js + Tailwind)

Mobile-first лендинг зі структурою hero → вигоди → відгуки → FAQ → форма → футер.

## Запуск локально

```bash
cd landing
cp .env.example .env.local
npm install
npm run dev
```

Відкрити [http://localhost:3000](http://localhost:3000).

## Налаштування env

| Змінна | Опис |
| --- | --- |
| `LEAD_WEBHOOK_URL` | URL для прийому заявок з форми. |
| `NEXT_PUBLIC_TIKTOK_PIXEL_ID` | TikTok Pixel ID (опційно). |
| `NEXT_PUBLIC_META_PIXEL_ID` | Meta Pixel ID (опційно). |
| `NEXT_PUBLIC_GTM_ID` | Google Tag Manager ID (опційно). |

## Деплой

### Vercel
1. Створити новий проєкт з папки `landing`.
2. Вказати build command: `npm run build`, output: `.next`.
3. Додати env змінні з `.env.example`.
4. Deploy.

### Netlify
1. Base directory: `landing`.
2. Build command: `npm run build`.
3. Publish directory: `.next`.
4. Додати env змінні.

## API

`POST /api/lead` приймає JSON `{ name, phone, comment }` і пересилає у webhook.

## Маркетинг

Пікселі TikTok, Meta та GTM підключаються лише якщо env змінні заповнені.

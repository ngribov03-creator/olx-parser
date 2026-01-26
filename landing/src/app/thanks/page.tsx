import Link from 'next/link';

export default function ThanksPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5">
      <div className="max-w-xl rounded-3xl bg-white p-8 text-center shadow-soft">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
          заявка прийнята
        </p>
        <h1 className="mt-4 text-3xl font-semibold text-ink-900">
          Дякуємо! Ми вже готуємо відповідь
        </h1>
        <p className="mt-3 text-sm text-slate-600">
          Наш менеджер звʼяжеться з вами найближчим часом, щоб уточнити деталі та
          запропонувати рішення.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex rounded-2xl bg-brand-500 px-6 py-3 text-sm font-semibold text-white"
        >
          Повернутися на головну
        </Link>
      </div>
    </main>
  );
}

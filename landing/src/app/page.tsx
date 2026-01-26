import LeadForm from '@/components/LeadForm';

const benefits = [
  {
    title: 'Фокус на мобільних лідах',
    description:
      'Побудовано навколо першого дотику на смартфоні: короткий шлях до заявки та швидке завантаження.'
  },
  {
    title: 'Продажна логіка блоків',
    description:
      'Hero, вигоди, відгуки, FAQ — усе, щоб посилити довіру та зняти заперечення.'
  },
  {
    title: 'Готовність до реклами',
    description:
      'Підключення TikTok Pixel, Meta Pixel і GTM через конфіг. Легко масштабувати кампанії.'
  }
];

const testimonials = [
  {
    name: 'Анна, онлайн-магазин',
    quote:
      'Після запуску цієї сторінки конверсія в заявку виросла до 18%. Люди стали залишати більше контактів.'
  },
  {
    name: 'Олег, сервіс доставки',
    quote:
      'Лендінг виглядає сучасно, а форма дійсно проста. Запити почали приходити вже з першого дня.'
  },
  {
    name: 'Катерина, консультації',
    quote:
      'Сподобалося, що все чітко: вигоди + відповіді на питання + швидкий контакт. Клієнти не губляться.'
  }
];

const faqs = [
  {
    question: 'Скільки часу потрібно на запуск?',
    answer:
      'Базова версія стартує одразу. Далі налаштовуємо тексти, вебхук і трекінг під вашу задачу.'
  },
  {
    question: 'Чи можна підключити декілька джерел трафіку?',
    answer:
      'Так. У конфігу задаються Meta, TikTok та GTM. Додаємо UTM та події за потребою.'
  },
  {
    question: 'Як працює форма заявки?',
    answer:
      'Контакти летять у ваш webhook. Далі їх можна пересилати у CRM або Telegram.'
  },
  {
    question: 'Чи є підтвердження для клієнта?',
    answer:
      'Так, після відправки людина бачить success state і переходить на сторінку /thanks.'
  }
];

export default function HomePage() {
  return (
    <main className="min-h-screen bg-slate-50">
      <section className="relative overflow-hidden bg-gradient-to-br from-ink-900 via-slate-900 to-slate-800 text-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 py-14 sm:px-6 lg:flex-row lg:items-center lg:py-20">
          <div className="flex-1">
            <p className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs uppercase tracking-[0.2em] text-white/70">
              DirectSell / Mobile-first
            </p>
            <h1 className="mt-5 text-3xl font-semibold leading-tight sm:text-4xl lg:text-5xl">
              Продаючий лендінг для швидких заявок
            </h1>
            <p className="mt-4 text-base text-white/80 sm:text-lg">
              Зібрали структуру, яка переконує: чітка цінність, соціальний доказ і форма,
              що не відлякує. Ідеально для тесту трафіку та масштабування реклами.
            </p>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button className="rounded-2xl bg-accent-500 px-6 py-3 text-base font-semibold text-ink-900 shadow-soft">
                Запустити кампанію
              </button>
              <div className="rounded-2xl border border-white/20 px-6 py-3 text-sm text-white/70">
                Перший контакт за 2 хвилини
              </div>
            </div>
            <div className="mt-6 grid gap-4 text-sm text-white/70 sm:grid-cols-2">
              <div className="rounded-2xl border border-white/10 px-4 py-3">
                98% показників Core Web Vitals
              </div>
              <div className="rounded-2xl border border-white/10 px-4 py-3">
                Форма під UA номер + згода
              </div>
            </div>
          </div>
          <div className="flex-1">
            <div className="rounded-3xl bg-white/10 p-6 backdrop-blur">
              <div className="rounded-2xl bg-white p-5 text-slate-900">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                  Кроки запуску
                </p>
                <ul className="mt-4 grid gap-4 text-sm">
                  <li className="rounded-2xl bg-slate-50 px-4 py-3">
                    1. Узгоджуємо оффер і аудиторію
                  </li>
                  <li className="rounded-2xl bg-slate-50 px-4 py-3">
                    2. Підключаємо трекінг і webhook
                  </li>
                  <li className="rounded-2xl bg-slate-50 px-4 py-3">
                    3. Запускаємо трафік і збираємо заявки
                  </li>
                </ul>
                <p className="mt-4 text-xs text-slate-400">
                  Відгуки та FAQ нижче допоможуть закрити типові сумніви.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-14 sm:px-6">
        <h2 className="section-title">Чому клієнти залишають заявку тут</h2>
        <p className="section-subtitle">
          Ми повторюємо логіку живого менеджера: пояснюємо, що ви отримаєте, і
          закриваємо заперечення ще до заявки.
        </p>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {benefits.map((item) => (
            <div
              key={item.title}
              className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <h3 className="text-lg font-semibold text-ink-900">
                {item.title}
              </h3>
              <p className="mt-3 text-sm text-slate-600">{item.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-white">
        <div className="mx-auto max-w-6xl px-5 py-14 sm:px-6">
          <h2 className="section-title">Відгуки, які продають замість вас</h2>
          <p className="section-subtitle">
            Соціальний доказ знімає питання довіри та підсилює рішення залишити
            контакт.
          </p>
          <div className="mt-8 grid gap-6 md:grid-cols-3">
            {testimonials.map((item) => (
              <figure
                key={item.name}
                className="flex flex-col justify-between rounded-3xl border border-slate-100 bg-slate-50 p-6"
              >
                <blockquote className="text-sm text-slate-600">
                  “{item.quote}”
                </blockquote>
                <figcaption className="mt-4 text-xs font-semibold text-slate-500">
                  {item.name}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-14 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1.1fr,0.9fr]">
          <div>
            <h2 className="section-title">FAQ перед запуском</h2>
            <p className="section-subtitle">
              Відповідаємо на ключові запити, щоб рішення про заявку було простим.
            </p>
            <div className="mt-6 grid gap-4">
              {faqs.map((item) => (
                <div
                  key={item.question}
                  className="rounded-3xl border border-slate-200 bg-white p-5"
                >
                  <h3 className="text-base font-semibold text-ink-900">
                    {item.question}
                  </h3>
                  <p className="mt-2 text-sm text-slate-600">{item.answer}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="rounded-3xl bg-ink-900 p-6 text-white">
              <h2 className="text-2xl font-semibold">
                Заповніть форму — і ми повернемось з планом
              </h2>
              <p className="mt-3 text-sm text-white/70">
                Коротка заявка, щоб розрахувати бюджет, комунікацію та старт кампанії.
              </p>
              <LeadForm />
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-10 text-sm text-slate-500 sm:px-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="font-semibold text-ink-900">DirectSell</p>
            <p>Mobile-first лендінги для швидких продажів.</p>
          </div>
          <div className="flex flex-col gap-2 md:items-end">
            <span>Працюємо по Україні</span>
            <span>support@directsell.ua</span>
          </div>
        </div>
      </footer>
    </main>
  );
}

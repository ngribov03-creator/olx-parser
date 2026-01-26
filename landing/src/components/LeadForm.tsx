'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

const initialState = {
  name: '',
  phone: '',
  comment: '',
  policy: false
};

const phonePattern = /^(\+?380|0)\d{9}$/;

export default function LeadForm() {
  const [formData, setFormData] = useState(initialState);
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>(
    'idle'
  );
  const [errorMessage, setErrorMessage] = useState('');
  const router = useRouter();

  const validation = useMemo(() => {
    const nameValid = formData.name.trim().length >= 2;
    const phoneValid = phonePattern.test(formData.phone.trim());
    const policyValid = formData.policy;

    return {
      nameValid,
      phoneValid,
      policyValid,
      isValid: nameValid && phoneValid && policyValid
    };
  }, [formData]);

  const updateField = (
    field: keyof typeof initialState,
    value: string | boolean
  ) => {
    setFormData((prev) => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validation.isValid || status === 'sending') {
      setErrorMessage('Перевірте дані форми та погодження з політикою.');
      return;
    }

    setStatus('sending');
    setErrorMessage('');

    try {
      const response = await fetch('/api/lead', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: formData.name.trim(),
          phone: formData.phone.trim(),
          comment: formData.comment.trim()
        })
      });

      if (!response.ok) {
        throw new Error('bad response');
      }

      setStatus('success');
      setTimeout(() => {
        router.push('/thanks');
      }, 1400);
      setFormData(initialState);
    } catch (error) {
      setStatus('error');
      setErrorMessage('Не вдалося відправити заявку. Спробуйте ще раз.');
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-6 grid gap-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-soft"
    >
      <div>
        <label className="text-sm font-medium text-slate-700" htmlFor="name">
          Імʼя
        </label>
        <input
          id="name"
          type="text"
          value={formData.name}
          onChange={(event) => updateField('name', event.target.value)}
          className="mt-1 w-full rounded-2xl border border-slate-200 px-4 py-3 text-base outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
          placeholder="Як до вас звертатись"
          required
        />
      </div>
      <div>
        <label className="text-sm font-medium text-slate-700" htmlFor="phone">
          Телефон (UA)
        </label>
        <input
          id="phone"
          type="tel"
          value={formData.phone}
          onChange={(event) => updateField('phone', event.target.value)}
          className="mt-1 w-full rounded-2xl border border-slate-200 px-4 py-3 text-base outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
          placeholder="+380 67 000 00 00"
          required
        />
        {!validation.phoneValid && formData.phone.length > 0 ? (
          <p className="mt-1 text-xs text-rose-500">
            Формат: +380XXXXXXXXX або 0XXXXXXXXX
          </p>
        ) : null}
      </div>
      <div>
        <label className="text-sm font-medium text-slate-700" htmlFor="comment">
          Коментар (опційно)
        </label>
        <textarea
          id="comment"
          value={formData.comment}
          onChange={(event) => updateField('comment', event.target.value)}
          className="mt-1 min-h-[120px] w-full resize-none rounded-2xl border border-slate-200 px-4 py-3 text-base outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
          placeholder="Що важливо врахувати у вашій заявці?"
        />
      </div>
      <label className="flex items-start gap-3 text-xs text-slate-600">
        <input
          type="checkbox"
          checked={formData.policy}
          onChange={(event) => updateField('policy', event.target.checked)}
          className="mt-1 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          required
        />
        Погоджуюсь з політикою конфіденційності та обробкою персональних даних.
      </label>
      {errorMessage ? (
        <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">
          {errorMessage}
        </p>
      ) : null}
      {status === 'success' ? (
        <p className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-600">
          Дякуємо! Ваша заявка прийнята. Переадресуємо на сторінку підтвердження.
        </p>
      ) : null}
      <button
        type="submit"
        disabled={!validation.isValid || status === 'sending'}
        className="w-full rounded-2xl bg-brand-500 px-6 py-3 text-base font-semibold text-white transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {status === 'sending' ? 'Надсилаємо...' : 'Отримати консультацію'}
      </button>
    </form>
  );
}

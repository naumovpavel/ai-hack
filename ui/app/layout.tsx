import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(
    'https://signal-hiring-demo.salty-gecko-5939.chatgpt.site',
  ),
  referrer: 'no-referrer',
  title: 'Signal — доказательные AI-интервью',
  description:
    'Сквозной процесс найма: настройка интервью, прохождение и проверяемая AI-оценка.',
  openGraph: {
    title: 'Signal — доказательные AI-интервью',
    description:
      'Вопрос, ответ, evidence и человеческое решение — в одном процессе.',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'Signal' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Signal — доказательные AI-интервью',
    description:
      'Вопрос, ответ, evidence и человеческое решение — в одном процессе.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}

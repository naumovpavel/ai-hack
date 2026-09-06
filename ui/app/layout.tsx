import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(
    'https://signal-hiring-demo.wiftwift.chatgpt.site',
  ),
  referrer: 'no-referrer',
  icons: {
    icon: { url: '/slopy-logo.jpg', type: 'image/jpeg' },
    apple: '/slopy-logo.jpg',
  },
  title: 'Slopy — доказательные AI-интервью',
  description:
    'Сквозной процесс найма: настройка интервью, прохождение и проверяемая AI-оценка.',
  openGraph: {
    title: 'Slopy — доказательные AI-интервью',
    description:
      'Вопрос, ответ, evidence и человеческое решение — в одном процессе.',
    images: [{ url: '/slopy-logo.jpg', width: 512, height: 512, alt: 'Slopy' }],
  },
  twitter: {
    card: 'summary',
    title: 'Slopy — доказательные AI-интервью',
    description:
      'Вопрос, ответ, evidence и человеческое решение — в одном процессе.',
    images: ['/slopy-logo.jpg'],
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

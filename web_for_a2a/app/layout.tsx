import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'DeepResearch A2A Web Client',
  description: '基于Next.js的DeepResearch A2A流式客户端',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh">
      <body>
        {children}
      </body>
    </html>
  );
}
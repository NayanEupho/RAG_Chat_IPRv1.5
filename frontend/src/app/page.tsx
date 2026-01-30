import { Suspense } from 'react';
import ChatInterface from "@/components/ChatInterface";

export default function Home() {
  return (
    <main>
      <Suspense fallback={<div>Loading...</div>}>
        <ChatInterface />
      </Suspense>
    </main>
  );
}

"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Chat from "@/components/Chat";

export const dynamic = 'force-dynamic';

function ChatWrapper() {
    const searchParams = useSearchParams();
    const sessionId = searchParams.get("session") || undefined;

    return <Chat sessionId={sessionId} />;
}

export default function Home() {
    return (
        <Suspense fallback={<div className="flex-center h-full">Loading env...</div>}>
            <ChatWrapper />
        </Suspense>
    );
}

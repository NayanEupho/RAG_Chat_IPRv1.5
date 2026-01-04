"use client";

import Link from "next/link";

export default function ErrorPage() {
    return (
        <div className="min-h-screen flex flex-col items-center justify-center bg-[#0a0a0f] text-white p-8">
            <div className="text-center max-w-md">
                {/* Error Icon */}
                <div className="w-20 h-20 mx-auto mb-8 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                    <span className="text-4xl">⚠️</span>
                </div>

                <h1 className="text-4xl font-bold mb-4 bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent">
                    Something went wrong
                </h1>

                <p className="text-white/50 mb-8 leading-relaxed">
                    An unexpected error occurred. This could be due to a network issue or the backend server not running.
                </p>

                <div className="flex flex-col gap-3">
                    <Link
                        href="/"
                        className="px-6 py-3 bg-indigo-500/80 hover:bg-indigo-500 rounded-xl text-white font-medium transition-colors"
                    >
                        Go to Home
                    </Link>
                    <button
                        onClick={() => window.location.reload()}
                        className="px-6 py-3 bg-white/5 hover:bg-white/10 rounded-xl text-white/70 font-medium transition-colors border border-white/10"
                    >
                        Try Again
                    </button>
                </div>
            </div>
        </div>
    );
}

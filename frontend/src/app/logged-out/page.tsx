import React from 'react';
import Link from 'next/link';

export default function LoggedOut() {
    return (
        <div className="flex h-screen w-full items-center justify-center bg-gray-900 text-white">
            <div className="text-center space-y-6 p-8 rounded-lg bg-gray-800 shadow-xl max-w-md w-full border border-gray-700">
                <div className="w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center mx-auto mb-4 ring-1 ring-blue-500/20">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="w-8 h-8 text-blue-400"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    >
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                        <polyline points="16 17 21 12 16 7" />
                        <line x1="21" y1="12" x2="9" y2="12" />
                    </svg>
                </div>

                <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">
                    Successfully Signed Out
                </h1>

                <p className="text-gray-400 text-lg">
                    You have been securely logged out of your session.
                </p>

                <div className="pt-4">
                    <Link
                        href="/saml/login"
                        className="inline-flex w-full items-center justify-center rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition-all hover:bg-blue-500 hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-gray-900 shadow-lg shadow-blue-500/20"
                    >
                        Sign In Again
                    </Link>
                </div>

                <p className="text-xs text-gray-500 mt-8">
                    To completely sign out of your organization&apos;s Single Sign-On, please close all browser windows.
                </p>
            </div>
        </div>
    );
}

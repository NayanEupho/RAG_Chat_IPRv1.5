import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import CommandMenu from "@/components/CommandMenu";
import { Toaster } from "sonner";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
    title: "DevOps Agent",
    description: "AI-powered DevOps Assistant",
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
            <body>
                <div className="app-container">
                    <Sidebar />
                    <main>
                        <div className="aurora-bg" />
                        <div className="layout-content">
                            {children}
                        </div>
                    </main>
                </div>
                <CommandMenu />
                <Toaster theme="dark" position="bottom-right" />
            </body>
        </html>
    );
}

import { Suspense } from 'react';
import ChatInterface from "@/components/ChatInterface";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";


export default async function Home() {
  const cookieStore = cookies();
  const session = (await cookieStore).get("saml_session");

  const useSaml = process.env.NEXT_PUBLIC_USE_SAML_LOGIN === "true";

  if (useSaml && !session) {
    redirect("/saml/login");
  }


  // export default function Home() {
  return (
    <main>
      <Suspense fallback={<div>Loading...</div>}>
        <ChatInterface />
      </Suspense>
    </main>
  );
}


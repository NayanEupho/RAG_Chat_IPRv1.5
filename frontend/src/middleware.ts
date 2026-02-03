import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
export function middleware(request: NextRequest) {
    // Check for the session cookie
    console.log("Inside Middleware");
    const session = request.cookies.get('saml_session');

    // If no cookie, redirect to SAML login
    if (!session) {
        // We use the backend login route: /saml/login
        // Nginx will proxy this to the backend
        console.log("No Session found, redirecting to SAML login page");
        const loginUrl = new URL('/saml/login', request.url);

        // Add the current page as the 'next' parameter
        loginUrl.searchParams.set('next', request.nextUrl.pathname);

        return NextResponse.redirect(loginUrl);
    }

    console.log("Session found - User is already logged in");
    console.log(session?.value);
    return NextResponse.next();
}
// Protect all routes except static assets and API
export const config = {
    matcher: [
        '/((?!api|_next/static|_next/image|favicon.ico).*)',
    ],
};
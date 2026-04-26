import { NextResponse, type NextRequest } from "next/server";

const isLocal = process.env.NEXT_PUBLIC_MODE === "local";

export async function middleware(request: NextRequest) {
  if (isLocal) {
    // Local mode: no auth, all routes accessible
    // Redirect root to /wikis
    if (request.nextUrl.pathname === "/") {
      const url = request.nextUrl.clone();
      url.pathname = "/wikis";
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  // Hosted mode: Supabase session management
  const { updateSession } = await import("@/lib/supabase/middleware");
  return await updateSession(request);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};

---
name: opsora-nextjs
description: Next.js SaaS engineering patterns — server-side token proxy, mobile-first UI, API route validation, middleware auth, Supabase integration. Based on patterns from opsora-landing, opsora-dashboard, and operatoros/web.
---

# Skill: Next.js SaaS Engineer

Build and improve Next.js applications following production-tested patterns from the Opsora ecosystem. Three Next.js apps exist in the codebase — use their patterns as reference.

## When to use

- Building new Next.js pages or API routes
- Fixing build errors (JSX, TypeScript, module resolution)
- Adding authentication or authorization
- Integrating with external APIs (never expose tokens client-side)
- Optimizing for mobile-first (most Indonesian users are on phones)

## Reference apps in the ecosystem

| App | Repo | Stack | Auth |
|-----|------|-------|------|
| opsora-landing | `opsora-landing/` | Next.js + Tailwind | None (public) |
| opsora-dashboard | `opsora-dashboard/` | Next.js 16 + Supabase | Supabase Auth + RLS |
| operatoros/web | `opsora/operatoros/apps/web/` | Next.js + Fastify proxy | Session-based (scrypt) |

## Hard rules

1. **Server-side tokens only** — API keys, payment secrets, and auth tokens NEVER in client bundle
   - Use API routes (`app/api/`) as server-side proxies
   - Use `server-only` package for sensitive imports
   - Never use `NEXT_PUBLIC_` prefix for secrets

2. **Mobile-first UI** — Target 3GB RAM Android phones
   - No heavy client-side JS
   - Prefer server components over client components
   - Use streaming SSR for fast first paint
   - Test on 360px width minimum

3. **Validation at boundaries** — Validate all external input
   - API routes: validate request body with zod or manual checks
   - Forms: validate both client (UX) and server (security)
   - Never trust `NEXT_PUBLIC_` env vars for authorization

4. **Error handling** — Generic errors to users, detailed errors to logs
   - Client sees: "Something went wrong. Please try again."
   - Server logs: full error with stack trace, request ID, timestamp

## API route proxy pattern

The standard pattern for hiding API tokens (from operatoros/web):

```typescript
// app/api/proxy/[...path]/route.ts
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL; // server-only
const API_TOKEN = process.env.API_TOKEN;     // server-only

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  const url = `${BACKEND_URL}/${params.path.join('/')}`;
  const res = await fetch(url, {
    headers: { 'Authorization': `Bearer ${API_TOKEN}` },
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

// Repeat for POST, PUT, DELETE...
```

## Middleware auth pattern

From opsora-dashboard:

```typescript
// middleware.ts
import { createMiddlewareClient } from '@supabase/auth-helpers-nextjs';
import { NextResponse } from 'next/server';

export async function middleware(req: NextRequest) {
  const res = NextResponse.next();
  const supabase = createMiddlewareClient({ req, res });
  const { data: { session } } = await supabase.auth.getSession();

  // Protected routes
  if (!session && req.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/login', req.url));
  }
  return res;
}

export const config = { matcher: ['/dashboard/:path*', '/settings/:path*'] };
```

## Build troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Module not found` | Missing dependency or wrong import path | `npm install` or fix import |
| `Hydration failed` | Server/client HTML mismatch | Check conditional rendering, dates, IDs |
| `Type error: X is not assignable` | TypeScript strict mode | Fix types or add type assertion |
| `Build exceeded maximum duration` | Too many pages/API routes | Use ISR or on-demand revalidation |
| `Cannot find module 'server-only'` | Missing package | `npm install server-only` |

## Tools used

| Tool | Purpose |
|------|---------|
| `glob_search` | Find page files, API routes, middleware |
| `grep_search` | Find env var usage, API endpoints, imports |
| `read_file` | Read existing patterns from reference apps |
| `edit_file` | Modify pages, routes, components |
| `run_command` | Run build, lint, type-check |

import {NextResponse,type NextRequest} from "next/server";
import {validationIdentity} from "@/lib/validation-auth.mjs";
export function proxy(request:NextRequest){
 const pathname=request.nextUrl.pathname;
 const forwarded=new Headers(request.headers);
 for(const key of [...forwarded.keys()])if(key.startsWith("oai-authenticated-") || key==="x-middleware-subrequest")forwarded.delete(key);
 // The public cash portal has its own session and CSRF boundary. Existing
 // application routes retain the legacy private validation guard.
 if(pathname==="/api/health"||pathname==="/cash"||pathname.startsWith("/cash/")||pathname==="/api/cash"||pathname.startsWith("/api/cash/"))return NextResponse.next({request:{headers:forwarded}});
 if(!validationIdentity(request.headers.get("authorization")))return new NextResponse("Private validation authentication required",{status:401,headers:{"WWW-Authenticate":'Basic realm="Al-Rifai private validation", charset="UTF-8"',"Cache-Control":"no-store"}});
 return NextResponse.next({request:{headers:forwarded}});
}
// The candidate host applies this same Basic guard before named authentication.
// Keep its request bodies out of Next proxy cloning during early denial/cancellation.
export const config={matcher:["/((?!candidate-api(?:/|$)|_next/static|_next/image|favicon.svg|file.svg|globe.svg|window.svg).*)"]};

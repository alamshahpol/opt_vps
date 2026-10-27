import {headers} from "next/headers";
import {validationIdentity} from "@/lib/validation-auth.mjs";
export type ChatGPTUser={userId:string;displayName:string;email:string;fullName:string|null};
// Compatibility names only: identity comes from local Basic auth, never Sites headers.
export async function getChatGPTUser():Promise<ChatGPTUser|null>{return validationIdentity((await headers()).get("authorization"));}
export async function requireChatGPTUser(returnTo:string):Promise<ChatGPTUser>{void returnTo;const user=await getChatGPTUser();if(!user)throw new Error("Private validation authentication required");return user;}

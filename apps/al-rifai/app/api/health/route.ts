import {database} from "@/db/raw";
export const dynamic="force-dynamic";
export async function GET(){try{await database().first("SELECT 1 AS ready");return Response.json({status:"ok"},{headers:{"Cache-Control":"no-store"}});}catch{return Response.json({status:"unavailable"},{status:503});}}

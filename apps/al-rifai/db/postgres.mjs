import pg from 'pg';
import {readFileSync} from 'node:fs';
export function createPool({readOnly=true,schema=process.env.PGSCHEMA || 'public',user='alrifai_app'}={}){
 if(!/^[a-z][a-z0-9_]*$/.test(schema))throw new Error('Invalid database schema');
 if(!['alrifai_app','ir_review_runtime','alrifai_mirror_worker'].includes(user))throw new Error('Invalid database role');
 const passwordFile=user==='alrifai_mirror_worker'
  ?process.env.ALRIFAI_MIRROR_WORKER_PASSWORD_FILE
  :user==='ir_review_runtime'
   ?process.env.ALRIFAI_REVIEW_PASSWORD_FILE||'/etc/vps/apps/al-rifai/auth/pg-password'
   :process.env.PGPASSWORD_FILE||'/run/secrets/database_password';
 if(!passwordFile)throw new Error('Dedicated Mirror Worker password file is required');
 return new pg.Pool({host:process.env.PGHOST || 'vps-infra-postgres-1',port:5432,database:'alrifai',user,password:readFileSync(passwordFile,'utf8').trim(),max:5,connectionTimeoutMillis:5000,idleTimeoutMillis:10000,options:`-c search_path=${schema} -c statement_timeout=15000 -c default_transaction_read_only=${readOnly?'on':'off'}`,application_name:`al-rifai-${user}`});
}

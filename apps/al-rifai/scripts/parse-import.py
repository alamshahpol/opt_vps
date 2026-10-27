"""Parse original files only; no identity authority, ledger or network access."""
import sys,json,csv,io,base64,re,datetime,collections
job=json.load(sys.stdin);blob=base64.b64decode(job['content']);name=job['name'].lower();rows=[]
if name.endswith('.txt'):
 messages=[]
 for line in blob.decode('utf-8-sig').splitlines():
  m=re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4}), (\d{1,2}):(\d{2}) - ([^:]+): ?(.*)$',line)
  if m:
   day,month,year,hour,minute,sender,text=m.groups()
   try:at=datetime.datetime(int(year),int(month),int(day),int(hour),int(minute),tzinfo=datetime.timezone(datetime.timedelta(hours=6))).isoformat()
   except ValueError:at=None
   messages.append({'sourceTime':at,'senderLabel':sender,'text':text,'originalHeader':line})
  elif messages:messages[-1]['text']+='\n'+line
 if not messages:raise ValueError('No supported DD/MM/YYYY 24-hour messages found; original retained')
 occurrence=collections.Counter()
 for m in messages:
  anchor=str(m['sourceTime'])+'|'+m['senderLabel'];occurrence[anchor]+=1;m['externalId']=anchor+'|occurrence:'+str(occurrence[anchor]);rows.append(m)
elif name.endswith('.csv'):rows=[dict(r) for r in csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))) ]
elif name.endswith('.json'):
 data=json.loads(blob);rows=data if isinstance(data,list) else data['records']
elif name.endswith('.xlsx'):
 import openpyxl
 book=openpyxl.load_workbook(io.BytesIO(blob),read_only=True,data_only=True)
 for sheet in book:
  it=iter(sheet.values);headers=[str(x or '') for x in next(it,[])];rows.extend({k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in zip(headers,r)} for r in it if any(v is not None for v in r))
else:raise ValueError('Use TXT/CSV/JSON/XLSX; document images require protected evidence review')
if len(rows)>50000:raise ValueError('At most 50000 source rows per file')
json.dump({'rows':rows,'kind':'conversation' if name.endswith('.txt') else 'structured'},sys.stdout,ensure_ascii=False,default=str)

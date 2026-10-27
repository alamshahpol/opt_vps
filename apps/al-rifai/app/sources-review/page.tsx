import type {Metadata} from 'next';
import {PlatformPage} from '@/app/platform/protected';
import SourcesReviewView from './view';

export const dynamic='force-dynamic';
export const metadata:Metadata={title:'Sources & Review · AL-RIFA’I'};

export default function Page(){
  return <PlatformPage pathname="/sources-review" label="Sources & Review">
    <SourcesReviewView/>
  </PlatformPage>;
}

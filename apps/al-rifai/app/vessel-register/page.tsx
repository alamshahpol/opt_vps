import type {Metadata} from 'next';
import {PlatformPage} from '@/app/platform/protected';
import VesselRegisterView from './view';

export const dynamic='force-dynamic';
export const metadata:Metadata={title:'Vessel Register · AL-RIFA’I'};

export default function Page(){
  return <PlatformPage pathname="/vessel-register" label="Vessel Register">
    <VesselRegisterView/>
  </PlatformPage>;
}

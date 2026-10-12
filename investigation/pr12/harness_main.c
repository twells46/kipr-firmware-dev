#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wallaby_spi_r4.h"
typedef struct { uint8_t rx[REG_ALL_COUNT]; uint8_t tx[REG_ALL_COUNT]; uint8_t guard[512]; } Mem;
extern Mem mem_m, mem_p; extern int adc_dirty_m, dig_dirty_m, adc_dirty_p, dig_dirty_p;
void handle_dma_m(void); void handle_dma_p(void);
static Mem base;
static int rej_p, rej_prev;
/* set by main(): 1 compares everything except MOT_DONE bits 7:4, which PR 12 + A10 reserves */
static int mask_both;
typedef struct { Mem m; int adc, dig; } Res;
static void run(const uint8_t *frame, Res *rm, Res *rp){
  mem_m = base; mem_p = base;
  memcpy(mem_m.rx, frame, REG_READABLE_COUNT); memcpy(mem_p.rx, frame, REG_READABLE_COUNT);
  adc_dirty_m=dig_dirty_m=adc_dirty_p=dig_dirty_p=0;
  handle_dma_m(); handle_dma_p();
  rm->m=mem_m; rm->adc=adc_dirty_m; rm->dig=dig_dirty_m;
  rp->m=mem_p; rp->adc=adc_dirty_p; rp->dig=dig_dirty_p;
  /* A10 reject counter lives in MOT_DONE bits 7:4; report it separately and
     mask it out of the register comparisons. */
  rej_p = rp->m.tx[REG_RW_MOT_DONE] >> 4;
  if (mask_both) rp->m.tx[REG_RW_MOT_DONE] = (rp->m.tx[REG_RW_MOT_DONE] & 0x0F) | (base.tx[REG_RW_MOT_DONE] & 0xF0);
  if (mask_both) rm->m.tx[REG_RW_MOT_DONE] = (rm->m.tx[REG_RW_MOT_DONE] & 0x0F) | (base.tx[REG_RW_MOT_DONE] & 0xF0);
}
static int same(Res*a,Res*b){ return !memcmp(&a->m,&b->m,sizeof(Mem)) && a->adc==b->adc && a->dig==b->dig; }
/* libwallaby-shaped frame: zero padded, n pairs */
static void frame(uint8_t *f, int n, const uint8_t *addr, const uint8_t *val){
  memset(f,0,REG_READABLE_COUNT); f[0]='J'; f[1]=4; f[2]=7; f[3]=n;
  for(int i=0;i<n;i++){ f[4+2*i]=addr[i]; f[5+2*i]=val[i]; }
  f[REG_READABLE_COUNT-1]='S';
}
/* expected effect of applying pairs to base, per the PR's intended semantics */
static int only_intended(Res *r, int n, const uint8_t *addr, const uint8_t *val){
  Mem e = base;
  memcpy(e.rx, r->m.rx, sizeof e.rx);
  for(int i=0;i<n;i++){ uint8_t a=addr[i], v=val[i];
    if(a<REG_RW_DIG_IN_H||a>=REG_ALL_COUNT) continue;
    if(a==REG_RW_MOT_MODES){ if(v&3)e.tx[REG_RW_MOT_DONE]&=~1; if(v&12)e.tx[REG_RW_MOT_DONE]&=~2; if(v&48)e.tx[REG_RW_MOT_DONE]&=~4; if(v&192)e.tx[REG_RW_MOT_DONE]&=~8; }
    e.tx[a]=v; }
  if (mask_both) e.tx[REG_RW_MOT_DONE] = (e.tx[REG_RW_MOT_DONE] & 0x0F) | (base.tx[REG_RW_MOT_DONE] & 0xF0);
  return !memcmp(&e,&r->m,sizeof(Mem));
}
int main(void){
  srand(1); for(size_t i=0;i<sizeof base;i++) ((uint8_t*)&base)[i]=rand();
  base.tx[0]='J'; base.tx[REG_RW_MOT_DONE]=0x0F;
  uint8_t f[REG_READABLE_COUNT], a[64], v[64]; Res rm, rp;
  long cnt, diff, diffin, bad;

  mask_both = getenv("MASK_DONE_HI") != NULL;
  printf("MOT_DONE bits 7:4 %s\n", mask_both ? "masked on both sides" : "compared");
  /* T1: every w8 (addr 0..255 x value 0..255) */
  cnt=diff=diffin=0;
  for(int ad=0;ad<256;ad++) for(int va=0;va<256;va++){ a[0]=ad;v[0]=va; frame(f,1,a,v); run(f,&rm,&rp); cnt++;
    if(!same(&rm,&rp)){ diff++; if(ad>=3&&ad<153) diffin++; } }
  printf("T1 w8 all addr/value: %ld frames, %ld differ, %ld differ with addr in 3..152\n",cnt,diff,diffin);

  /* T2: every w16 / w32 start address, 64 random values each */
  for(int w=2;w<=4;w+=2){ cnt=diff=diffin=0;
    for(int ad=0;ad<256;ad++) for(int k=0;k<64;k++){ for(int i=0;i<w;i++){a[i]=ad+i;v[i]=rand();} frame(f,w,a,v); run(f,&rm,&rp); cnt++;
      if(!same(&rm,&rp)){ diff++; if(ad>=3&&ad+w-1<153) diffin++; } }
    printf("T2 w%d: %ld frames, %ld differ, %ld differ with all addrs in 3..152\n",w*8,cnt,diff,diffin); }

  /* T3: read frames (count 0) */
  frame(f,0,a,v); run(f,&rm,&rp); printf("T3 read frame identical: %s\n", same(&rm,&rp)?"yes":"NO");

  /* T4: random valid multi-pair packets n=1..42 */
  cnt=diff=0; for(int it=0;it<200000;it++){ int n=1+rand()%42; for(int i=0;i<n;i++){a[i]=3+rand()%150; v[i]=rand();} frame(f,n,a,v); run(f,&rm,&rp); cnt++; if(!same(&rm,&rp)) diff++; }
  printf("T4 random valid n<=42: %ld frames, %ld differ\n",cnt,diff);

  /* T5: single-bit flips of the count byte for w8/w16/w32, valid addrs */
  long tot=0, m_J=0, p_J=0, p_ok=0, m_ok=0;
  for(int w=1;w<=4;w*=2) for(int bit=0;bit<8;bit++) for(int it=0;it<2000;it++){
    int ad=3+rand()%(150-w); for(int i=0;i<w;i++){a[i]=ad+i;v[i]=rand();}
    frame(f,w,a,v); f[3]^=1<<bit; run(f,&rm,&rp); tot++;
    if(rm.m.tx[0]!='J') m_J++; if(rp.m.tx[0]!='J') p_J++;
    if(only_intended(&rp,w,a,v)) p_ok++; if(only_intended(&rm,w,a,v)) m_ok++;
  }
  printf("T5 count bit flips: %ld frames; J cleared master=%ld pr12=%ld; exactly-intended-writes master=%ld pr12=%ld\n",tot,m_J,p_J,m_ok,p_ok);

  /* T6: oversized count with libwallaby zero padding: PR12 applies exactly the intended writes */
  bad=0;
  for(int c=5;c<256;c++){ for(int i=0;i<4;i++){a[i]=62+i;v[i]=rand();} frame(f,4,a,v); f[3]=c; run(f,&rm,&rp); if(!only_intended(&rp,4,a,v)) bad++; }
  printf("T6 count 5..255 over a w32 frame: pr12 not-exactly-intended=%ld\n",bad);

  /* T7: count>42 with NON-zero garbage padding: compare blast radius (bytes of tx changed) */
  long sm=0, sp=0; for(int it=0;it<20000;it++){ for(int i=0;i<REG_READABLE_COUNT;i++) f[i]=rand(); f[0]='J';f[1]=4;f[88]='S'; f[3]=43+rand()%213; run(f,&rm,&rp);
    for(int i=0;i<REG_ALL_COUNT;i++){ sm+= rm.m.tx[i]!=base.tx[i]; sp+= rp.m.tx[i]!=base.tx[i]; } }
  printf("T7 garbage packets count>42: mean tx bytes changed master=%.1f pr12=%.1f\n", sm/20000.0, sp/20000.0);

  /* T8: guard region (memory past aTxBuffer) ever written? */
  long gm=0,gp=0; for(int it=0;it<200000;it++){ for(int i=0;i<REG_READABLE_COUNT;i++) f[i]=rand(); f[0]='J';f[1]=4;f[88]='S'; run(f,&rm,&rp);
    gm+= memcmp(rm.m.guard,base.guard,512)!=0; gp+= memcmp(rp.m.guard,base.guard,512)!=0; }
  printf("T8 random packets writing past aTxBuffer: master=%ld pr12=%ld of 200000\n",gm,gp);

  /* T9: count 128..169 over a non-zero body: in-range writes applied, master vs pr12 */
  { long worse=0, better=0; for(int c=128;c<170;c++){ memset(f,0x30,sizeof f); f[0]='J';f[1]=4;f[3]=c;f[88]='S'; run(f,&rm,&rp);
      int nm=0,np=0; for(int i=0;i<REG_ALL_COUNT;i++){ nm+=rm.m.tx[i]!=base.tx[i]; np+=rp.m.tx[i]!=base.tx[i]; }
      if(np>nm) worse++; if(np<nm) better++;
      if(c==128) printf("T9 count=128 body=0x30: master changed %d tx bytes, pr12 changed %d (reg48=0x%02x)\n",nm,np,rp.m.tx[48]); }
    printf("T9 counts 128..169 body 0x30: pr12 changes more bytes in %ld, fewer in %ld\n",worse,better);
    double sm=0,sp=0; worse=better=0; for(int it=0;it<42000;it++){ int c=128+it%42; for(int i=0;i<REG_READABLE_COUNT;i++) f[i]=rand(); f[0]='J';f[1]=4;f[3]=c;f[88]='S'; run(f,&rm,&rp);
      int nm=0,np=0; for(int i=0;i<REG_ALL_COUNT;i++){ nm+=rm.m.tx[i]!=base.tx[i]; np+=rp.m.tx[i]!=base.tx[i]; } sm+=nm; sp+=np; if(np>nm) worse++; if(np<nm) better++; }
    printf("T9b counts 128..169 random body: mean tx bytes changed master=%.1f pr12=%.1f; pr12 more in %ld/42000, fewer in %ld\n",sm/42000,sp/42000,worse,better); }

  /* T10: reject counter (A10) advances by exactly 1 per rejected packet, 0 otherwise */
  { long clean_adv=0, rej_miss=0, rej_extra=0; int last;
    #define STEP(expect_rej) do{ last=rej_p; run(f,&rm,&rp); int adv=(rej_p-last)&15; \
      if(!(expect_rej)&&adv) clean_adv++; if((expect_rej)&&adv!=1) rej_miss++; if(adv>1) rej_extra++; }while(0)
    for(int it=0;it<100000;it++){ int w=1<<(rand()%3); int ad=3+rand()%(150-w); for(int i=0;i<w;i++){a[i]=ad+i;v[i]=rand();} frame(f,w,a,v); STEP(0); }
    for(int bit=0;bit<8;bit++) for(int w=1;w<=4;w*=2){ int ad=3+rand()%146; for(int i=0;i<w;i++){a[i]=ad+i;v[i]=rand();} frame(f,w,a,v); f[3]^=1<<bit; STEP(f[3]>w); }
    for(int ad=0;ad<3;ad++){ a[0]=ad;v[0]=1; frame(f,1,a,v); STEP(1); }
    for(int ad=153;ad<256;ad++){ a[0]=ad;v[0]=1; frame(f,1,a,v); STEP(1); }
    printf("T10 reject counter: clean frames that advanced=%ld, rejected frames not advancing by 1=%ld\n",clean_adv,rej_miss); }
  return 0;
}

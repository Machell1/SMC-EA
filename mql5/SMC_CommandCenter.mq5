//+------------------------------------------------------------------+
//|                                          SMC_CommandCenter.mq5    |
//| On-chart command center for the SMC COMMAND DESK.                 |
//|                                                                   |
//| DRAW-ONLY indicator. Never touches orders. Each OnTimer it reads  |
//| a per-symbol command file the desk writes to the Common\Files     |
//| sandbox and renders a professional dashboard panel + SMC objects  |
//| (channel, OB/FVG/zone rectangles, EQH/EQL liquidity, BOS/CHoCH).  |
//| Writes a per-symbol ack file back so the desk can verify from chat.|
//| IPC mirrors TurtleModeA.mq5: FILE_COMMON, FILE_TXT|FILE_ANSI,      |
//| atomic temp+FileMove; semicolon line format (no JSON parser).     |
//+------------------------------------------------------------------+
#property copyright "SMC COMMAND DESK"
#property version   "1.10"
#property strict
#property indicator_chart_window
#property indicator_plots   0
#property indicator_buffers 0

//--- IPC inputs -----------------------------------------------------
input string InpCmdPrefix   = "cmd_SMC_";    // command file prefix (desk -> EA)
input string InpAckPrefix   = "ack_SMC_";    // ack file prefix (EA -> desk)
input string InpObjPrefix   = "SMCC_";        // chart-object name prefix
input int    InpTimerSec    = 2;              // poll period (seconds)

//--- panel styling --------------------------------------------------
input int    InpPanelX      = 14;             // panel X (px from corner)
input int    InpPanelY      = 16;             // panel Y
input int    InpPanelW      = 280;            // panel width
input int    InpRowH        = 15;             // data row height
input int    InpFontSize    = 9;              // body font size
input string InpFont        = "Segoe UI";     // label / header font
input string InpFontMono    = "Consolas";     // value font (aligned)
input color  InpHeaderBg    = C'24,68,138';   // header band
input color  InpPanelBg     = C'19,21,27';    // body background
input color  InpPanelEdge   = C'58,64,78';    // border / separators
input color  InpLabelText   = C'140,149,166'; // muted labels
input color  InpValueText   = C'226,232,240'; // values
input color  InpSecText     = C'122,162,247'; // section headers

//--- runtime state --------------------------------------------------
long   g_applied_seq = -1;
string g_cmd_file;
string g_ack_file;
bool   g_stale       = false;

//+------------------------------------------------------------------+
//| field helpers                                                    |
//+------------------------------------------------------------------+
int SplitLine(const string line,string &items[]){ return StringSplit(line,(ushort)';',items); }

string AfterNthDelim(const string line,const int nn)
{
   int pos=-1;
   for(int k=0;k<nn;k++){ pos=StringFind(line,";",pos+1); if(pos<0) return ""; }
   return StringSubstr(line,pos+1);
}

string Fit(const string s,const int maxc)
{
   if(StringLen(s)<=maxc) return s;
   return StringSubstr(s,0,maxc-1)+ShortToString(0x2026); // ellipsis
}

color ColorFromName(const string raw)
{
   string c=raw; StringToLower(c);
   if(c=="dodger"  || c=="blue")    return clrDodgerBlue;
   if(c=="crimson" || c=="red")     return clrCrimson;
   if(c=="orange"  || c=="amber")   return clrOrange;
   if(c=="gold"    || c=="yellow")  return clrGold;
   if(c=="lime"    || c=="green")   return clrLimeGreen;
   if(c=="teal"    || c=="cyan")    return clrLightSeaGreen;
   if(c=="slate"   || c=="gray"||c=="grey") return clrSlateGray;
   if(c=="silver")                  return clrSilver;
   if(c=="magenta" || c=="pink")    return clrMagenta;
   if(c=="white")                   return clrWhiteSmoke;
   return clrSlateGray;
}

datetime ParseTime(const string raw)
{
   if(raw=="" || raw=="0") return 0;
   string s=raw; StringReplace(s,"-","."); StringReplace(s,"T"," ");
   return StringToTime(s);
}

datetime CurrentBarTime()
{
   datetime t=iTime(_Symbol,_Period,0);
   if(t<=0) t=TimeCurrent();
   return t;
}

//+------------------------------------------------------------------+
//| atomic write to Common\Files (TurtleModeA pattern)               |
//+------------------------------------------------------------------+
bool AtomicWriteCommon(const string name,const string text)
{
   string tmp=name+".tmp";
   int f=FileOpen(tmp,FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(f==INVALID_HANDLE) return false;
   FileWriteString(f,text+"\r\n");
   FileFlush(f); FileClose(f);
   if(!FileMove(tmp,FILE_COMMON,name,FILE_COMMON|FILE_REWRITE)){
      FileDelete(tmp,FILE_COMMON); return false;
   }
   return true;
}

int CountDrawn()
{
   int c=0;
   string pfx=InpObjPrefix+"p_";
   for(int i=0;i<ObjectsTotal(0);i++){
      string nm=ObjectName(0,i);
      if(StringFind(nm,InpObjPrefix)!=0) continue;   // not ours
      if(StringFind(nm,pfx)==0) continue;            // panel object
      c++;
   }
   return c;
}

void WriteAck(const long applied,const int errors)
{
   double last=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(last<=0) last=iClose(_Symbol,_Period,0);
   string line="applied_seq="+IntegerToString(applied)+
               ";drawn_count="+IntegerToString(CountDrawn())+
               ";errors="+IntegerToString(errors)+
               ";stale="+(g_stale?"1":"0")+
               ";chart_last_price="+DoubleToString(last,_Digits)+
               ";server_epoch="+IntegerToString((long)TimeCurrent())+
               ";gmt_epoch="+IntegerToString((long)TimeGMT());
   AtomicWriteCommon(g_ack_file,line);
}

//+------------------------------------------------------------------+
//| primitive panel objects                                          |
//+------------------------------------------------------------------+
void Box(const string id,const int x,const int y,const int w,const int h,
         const color bg,const color edge)
{
   string n=InpObjPrefix+id;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,n,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,n,OBJPROP_YSIZE,h);
   ObjectSetInteger(0,n,OBJPROP_BGCOLOR,bg);
   ObjectSetInteger(0,n,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,n,OBJPROP_COLOR,edge);
   ObjectSetInteger(0,n,OBJPROP_BACK,false);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

void Lbl(const string id,const int x,const int y,const string text,
         const string font,const int size,const color clr,const int anchor)
{
   string n=InpObjPrefix+id;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetString (0,n,OBJPROP_TEXT,text);
   ObjectSetString (0,n,OBJPROP_FONT,font);
   ObjectSetInteger(0,n,OBJPROP_FONTSIZE,size);
   ObjectSetInteger(0,n,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,n,OBJPROP_ANCHOR,anchor);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

color ValueColor(const string key,const string val)
{
   string v=val; StringToLower(v);
   if(StringFind(v,"lockout")>=0 && StringFind(v,"none")<0) return C'240,142,90';
   if(StringFind(v,"halt")>=0 || StringFind(v,"fault")>=0)  return C'233,115,103';
   if(StringFind(v,"fail")>=0)     return C'233,115,103';
   if(StringFind(v,"pass")>=0)     return C'95,205,140';
   if(StringFind(v,"bull")>=0)     return C'95,205,140';
   if(StringFind(v,"bear")>=0)     return C'233,115,103';
   if(StringFind(v,"observe")>=0)  return C'226,200,120';
   return InpValueText;
}

//+------------------------------------------------------------------+
//| render the dashboard                                             |
//+------------------------------------------------------------------+
void RenderPanel(string &keys[],string &vals[],const int n,
                 const string htf,const string ltf,const long wepoch)
{
   int x=InpPanelX, y=InpPanelY, w=InpPanelW;
   int headerH=24, padT=5, padB=7, secH=16, valueX=x+92, maxc=24;

   int bodyH=padT;
   for(int i=0;i<n;i++) bodyH += (keys[i]=="__sec") ? secH : InpRowH;
   bodyH += padB;
   int totalH=headerH+bodyH;

   Box("p_body",x,y,w,totalH,InpPanelBg,InpPanelEdge);
   Box("p_head",x,y,w,headerH,InpHeaderBg,InpHeaderBg);

   color dot = g_stale ? C'229,83,75' : C'63,201,123';
   Lbl("p_dot",  x+11, y+headerH/2, ShortToString(0x25CF), InpFont, 10, dot, ANCHOR_LEFT);
   Lbl("p_title",x+25, y+headerH/2, "SMC COMMAND DESK",     InpFont, 9, clrWhite, ANCHOR_LEFT);
   string upd=(wepoch>0)? (TimeToString((datetime)wepoch,TIME_MINUTES)+"Z") : "";
   Lbl("p_sym",  x+w-10, y+headerH/2, _Symbol+" "+htf+(upd!=""? "  "+upd : ""), InpFontMono, 8, C'199,214,236', ANCHOR_RIGHT);

   int cy=y+headerH+padT;
   for(int i=0;i<n;i++){
      if(keys[i]=="__sec"){
         Box("p_sep"+IntegerToString(i), x+10, cy+4, w-20, 1, InpPanelEdge, InpPanelEdge);
         Lbl("p_k"+IntegerToString(i), x+12, cy+6, vals[i], InpFont, 7, InpSecText, ANCHOR_LEFT_UPPER);
         cy+=secH;
      } else {
         Lbl("p_k"+IntegerToString(i), x+13, cy, keys[i], InpFont, InpFontSize, InpLabelText, ANCHOR_LEFT_UPPER);
         color vc = g_stale ? C'120,126,140' : ValueColor(keys[i],vals[i]);
         Lbl("p_v"+IntegerToString(i), valueX, cy, Fit(vals[i],maxc), InpFontMono, InpFontSize, vc, ANCHOR_LEFT_UPPER);
         cy+=InpRowH;
      }
   }
}

void MiniPanel(const string msg,const color clr)
{
   ObjectsDeleteAll(0,InpObjPrefix);
   int x=InpPanelX,y=InpPanelY,w=InpPanelW,headerH=30;
   Box("p_body",x,y,w,headerH+30,InpPanelBg,InpPanelEdge);
   Box("p_head",x,y,w,headerH,InpHeaderBg,InpHeaderBg);
   Lbl("p_title",x+14,y+headerH/2,"SMC COMMAND DESK",InpFont,10,clrWhite,ANCHOR_LEFT);
   Lbl("p_msg",x+14,y+headerH+9,msg,InpFont,InpFontSize,clr,ANCHOR_LEFT_UPPER);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| object rendering                                                 |
//+------------------------------------------------------------------+
void DrawRectangle(const string id,const datetime t1,const double p1,
                   const double p2,const color clr)
{
   string n=InpObjPrefix+id;
   datetime rt=CurrentBarTime();
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_RECTANGLE,0,t1,p1,rt,p2);
   ObjectSetInteger(0,n,OBJPROP_TIME,0,t1);
   ObjectSetDouble (0,n,OBJPROP_PRICE,0,p1);
   ObjectSetInteger(0,n,OBJPROP_TIME,1,rt);
   ObjectSetDouble (0,n,OBJPROP_PRICE,1,p2);
   ObjectSetInteger(0,n,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,n,OBJPROP_FILL,true);
   ObjectSetInteger(0,n,OBJPROP_BACK,true);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

void DrawHRay(const string id,const datetime t1,const double p1,
              const color clr,const int style)
{
   string n=InpObjPrefix+id;
   datetime t2=t1+PeriodSeconds()*5;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_TREND,0,t1,p1,t2,p1);
   ObjectSetInteger(0,n,OBJPROP_TIME,0,t1);
   ObjectSetDouble (0,n,OBJPROP_PRICE,0,p1);
   ObjectSetInteger(0,n,OBJPROP_TIME,1,t2);
   ObjectSetDouble (0,n,OBJPROP_PRICE,1,p1);
   ObjectSetInteger(0,n,OBJPROP_RAY_RIGHT,true);
   ObjectSetInteger(0,n,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,n,OBJPROP_STYLE,style);
   ObjectSetInteger(0,n,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

void DrawTrend(const string id,const datetime t1,const double p1,
               const datetime t2,const double p2,const color clr)
{
   string n=InpObjPrefix+id;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_TREND,0,t1,p1,t2,p2);
   ObjectSetInteger(0,n,OBJPROP_TIME,0,t1);
   ObjectSetDouble (0,n,OBJPROP_PRICE,0,p1);
   ObjectSetInteger(0,n,OBJPROP_TIME,1,t2);
   ObjectSetDouble (0,n,OBJPROP_PRICE,1,p2);
   ObjectSetInteger(0,n,OBJPROP_RAY_RIGHT,true);
   ObjectSetInteger(0,n,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,n,OBJPROP_WIDTH,2);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

void DrawText(const string id,const datetime t1,const double p1,
              const string label,const color clr)
{
   string n=InpObjPrefix+id+"_t";
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_TEXT,0,t1,p1);
   ObjectSetInteger(0,n,OBJPROP_TIME,0,t1);
   ObjectSetDouble (0,n,OBJPROP_PRICE,0,p1);
   ObjectSetString (0,n,OBJPROP_TEXT,label);
   ObjectSetString (0,n,OBJPROP_FONT,InpFont);
   ObjectSetInteger(0,n,OBJPROP_FONTSIZE,InpFontSize);
   ObjectSetInteger(0,n,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,n,OBJPROP_ANCHOR,ANCHOR_LEFT);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

bool RenderObject(const string &f[],const int nf)
{
   if(nf<8) return false;
   string id=f[1], kind=f[2];
   datetime t1=ParseTime(f[3]); double p1=StringToDouble(f[4]);
   datetime t2=ParseTime(f[5]); double p2=StringToDouble(f[6]);
   color clr=ColorFromName(f[7]); string label=(nf>8)?f[8]:"";
   string ku=kind; StringToUpper(ku);
   if(t1<=0 && ku!="EQ") return false;

   if(ku=="OB" || ku=="FVG" || ku=="ZONE"){
      if(p1<=0 || p2<=0) return false;
      DrawRectangle(id,t1,MathMax(p1,p2),MathMin(p1,p2),clr); return true;
   }
   if(ku=="TREND"){
      if(t2<=0 || p1<=0 || p2<=0) return false;
      DrawTrend(id,t1,p1,t2,p2,clr); return true;
   }
   if(ku=="LIQ" || ku=="TARGET"){
      if(p1<=0) return false;
      DrawHRay(id,t1,p1,clr,STYLE_DOT); if(label!="") DrawText(id,t1,p1,label,clr); return true;
   }
   if(ku=="EQ"){
      if(p1<=0) return false;
      DrawHRay(id,(t1>0)?t1:CurrentBarTime(),p1,clr,STYLE_DASH); return true;
   }
   if(ku=="BOS" || ku=="CHOCH"){
      if(p1<=0) return false;
      DrawHRay(id,t1,p1,clr,STYLE_DASHDOT);
      DrawText(id,t1,p1,(label!="")?label:ku,clr); return true;
   }
   return false;
}

void ExtendRectangles()
{
   datetime rt=CurrentBarTime();
   for(int i=0;i<ObjectsTotal(0);i++){
      string n=ObjectName(0,i);
      if(StringFind(n,InpObjPrefix)!=0) continue;
      if(ObjectGetInteger(0,n,OBJPROP_TYPE)!=OBJ_RECTANGLE) continue;
      ObjectSetInteger(0,n,OBJPROP_TIME,1,rt);
   }
}

//+------------------------------------------------------------------+
//| main poll                                                        |
//+------------------------------------------------------------------+
void Poll()
{
   int h=FileOpen(g_cmd_file,FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h==INVALID_HANDLE){
      MiniPanel("waiting for desk command file...",C'150,156,170');
      WriteAck(g_applied_seq,0);
      return;
   }

   string lines[]; int nlines=0;
   while(!FileIsEnding(h)){
      string ln=FileReadString(h);
      if(StringLen(ln)==0) continue;
      ArrayResize(lines,nlines+1); lines[nlines++]=ln;
   }
   FileClose(h);
   if(nlines==0){ WriteAck(g_applied_seq,1); return; }

   long seq=-1, written_epoch=0, ttl=3600;
   string metasym="", htf="HTF", ltf="LTF";
   for(int i=0;i<nlines;i++){
      string fm[]; int nm=SplitLine(lines[i],fm);
      if(nm>=1 && fm[0]=="meta"){
         if(nm>2) seq=(long)StringToInteger(fm[2]);
         if(nm>3) written_epoch=(long)StringToInteger(fm[3]);
         if(nm>4) metasym=fm[4];
         if(nm>5) htf=fm[5];
         if(nm>6) ltf=fm[6];
         if(nm>7) ttl=(long)StringToInteger(fm[7]);
         break;
      }
   }

   if(metasym!="" && metasym!=_Symbol){
      MiniPanel("cmd symbol mismatch: "+metasym,C'233,115,103');
      WriteAck(g_applied_seq,1);
      return;
   }

   long now_gmt=(long)TimeGMT();
   g_stale=(written_epoch>0 && (now_gmt-written_epoch)>ttl);

   if(seq>=0 && seq<=g_applied_seq){
      ExtendRectangles();
      WriteAck(g_applied_seq,0);
      return;
   }

   ObjectsDeleteAll(0,InpObjPrefix);

   string pk[]; string pv[]; int npanel=0; int errors=0;
   for(int i=0;i<nlines;i++){
      string f[]; int nf=SplitLine(lines[i],f);
      if(nf<1) continue;
      if(f[0]=="panel"){
         if(nf<2) continue;
         ArrayResize(pk,npanel+1); ArrayResize(pv,npanel+1);
         pk[npanel]=f[1];
         pv[npanel]=(f[1]=="__sec")? ((nf>2)?f[2]:"") : AfterNthDelim(lines[i],2);
         npanel++;
      } else if(f[0]=="obj"){
         if(!RenderObject(f,nf)) errors++;
      }
   }

   RenderPanel(pk,pv,npanel,htf,ltf,written_epoch);

   g_applied_seq=seq;
   ChartRedraw(0);
   WriteAck(g_applied_seq,errors);
}

//+------------------------------------------------------------------+
//| lifecycle                                                        |
//+------------------------------------------------------------------+
int OnInit()
{
   g_cmd_file=InpCmdPrefix+_Symbol+".txt";
   g_ack_file=InpAckPrefix+_Symbol+".txt";
   g_applied_seq=-1;
   EventSetTimer(MathMax(1,InpTimerSec));
   Poll();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0,InpObjPrefix);
   ChartRedraw(0);
}

void OnTimer(){ Poll(); }

int OnCalculate(const int rates_total,const int prev_calculated,
                const datetime &time[],const double &open[],const double &high[],
                const double &low[],const double &close[],const long &tick_volume[],
                const long &volume[],const int &spread[])
{
   return rates_total;
}
//+------------------------------------------------------------------+

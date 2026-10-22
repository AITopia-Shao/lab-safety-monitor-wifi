package edu.labguard.pocket;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.net.URLEncoder;
import java.util.Enumeration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** DroidCam 负责相机；本应用集成 Wi-Fi 配对、连接、预览与实验台小屏，不再占用 Camera API。 */
public final class MainActivity extends Activity {
    private String baseUrl="",token="",manualHost="";
    private int port=4747;
    private WebView web,preview;
    private TextView status;
    private EditText endpoint,pairCode,phoneHost,phonePort;
    private boolean resumed=false;
    private volatile boolean returningFromCamera=false;
    private long returnDeadline=0,lastCameraLaunch=0;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy=new AtomicBoolean(false);
    private final Runnable poll=new Runnable(){public void run(){if(returningFromCamera&&SystemClock.elapsedRealtime()>returnDeadline)returningFromCamera=false;if((resumed||returningFromCamera)&&status!=null)refreshStatus();handler.postDelayed(this,1200);}};

    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        SharedPreferences savedConfig=getPreferences(MODE_PRIVATE);
        baseUrl=savedConfig.getString("server","");token=savedConfig.getString("token","");
        manualHost=savedConfig.getString("host","");port=savedConfig.getInt("port",4747);
        readIntent(getIntent());
        if(validEndpoint(baseUrl)&&token.length()>=8)showMonitor();else showConnection();
        handler.post(poll);
    }

    private static boolean privateV4(String value){
        if(value==null||!value.matches("[0-9.]+"))return false;
        try{
            String[] parts=value.split("\\.");if(parts.length!=4)return false;
            int[] n=new int[4];for(int i=0;i<4;i++){n[i]=Integer.parseInt(parts[i]);if(n[i]<0||n[i]>255)return false;}
            return n[0]==10||(n[0]==192&&n[1]==168)||(n[0]==172&&n[1]>=16&&n[1]<=31);
        }catch(Exception e){return false;}
    }
    private boolean validEndpoint(String value){
        try{Uri uri=Uri.parse(value);return "http".equals(uri.getScheme())&&privateV4(uri.getHost())&&uri.getUserInfo()==null&&uri.getQuery()==null&&uri.getFragment()==null&&(uri.getPath()==null||uri.getPath().isEmpty()||uri.getPath().equals("/"));}
        catch(Exception e){return false;}
    }
    private void readIntent(Intent intent){
        String server=intent.getStringExtra("server"),code=intent.getStringExtra("token");
        if(server!=null&&code!=null&&validEndpoint(server)&&code.length()>=8&&code.length()<=128){baseUrl=server.replaceAll("/+$","");token=code;saveConfig();}
    }
    private void saveConfig(){getPreferences(MODE_PRIVATE).edit().putString("server",baseUrl).putString("token",token).putString("host",manualHost).putInt("port",port).apply();}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);readIntent(intent);showMonitor();if(resumed)connectCamera();}

    private TextView text(String value,int size){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(0xff263255);v.setPadding(14,8,14,8);return v;}
    private LinearLayout root(int orientation){
        LinearLayout root=new LinearLayout(this);root.setOrientation(orientation);root.setBackgroundColor(0xffe1f5fe);
        root.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});return root;
    }
    private void clearViews(){
        status=null;
        if(web!=null){web.stopLoading();web.destroy();web=null;}
        if(preview!=null){preview.stopLoading();preview.destroy();preview=null;}
    }
    private void showConnection(){
        clearViews();LinearLayout root=root(LinearLayout.VERTICAL);root.setPadding(20,12,20,12);
        root.addView(text("实验台随身小屏 · DroidCam Wi-Fi",22));
        root.addView(text("电脑连接手机热点或同一 Wi-Fi。输入电脑主控提供的地址与配对码；先打开 DroidCam，再返回本小屏。",14));
        endpoint=new EditText(this);endpoint.setSingleLine(true);endpoint.setHint("电脑地址，例如 http://192.168.43.100:8080");endpoint.setText(baseUrl);root.addView(endpoint);
        pairCode=new EditText(this);pairCode.setSingleLine(true);pairCode.setHint("电脑的 Wi-Fi 配对码");pairCode.setInputType(129);pairCode.setText(token);root.addView(pairCode);
        LinearLayout row=new LinearLayout(this);row.setOrientation(LinearLayout.HORIZONTAL);
        phoneHost=new EditText(this);phoneHost.setSingleLine(true);phoneHost.setHint("手机 IP：留空自动识别");phoneHost.setText(manualHost);row.addView(phoneHost,new LinearLayout.LayoutParams(0,-2,3));
        phonePort=new EditText(this);phonePort.setSingleLine(true);phonePort.setInputType(2);phonePort.setText(Integer.toString(port));row.addView(phonePort,new LinearLayout.LayoutParams(0,-2,1));root.addView(row);
        Button connect=new Button(this);connect.setText("保存并连接小屏 / DroidCam");connect.setOnClickListener(v->{
            String target=endpoint.getText().toString().trim();if(!target.startsWith("http://"))target="http://"+target;
            String code=pairCode.getText().toString().trim(),host=phoneHost.getText().toString().trim();
            int p;try{p=Integer.parseInt(phonePort.getText().toString());}catch(Exception e){p=0;}
            if(!validEndpoint(target)||code.length()<8||code.length()>128||(!host.isEmpty()&&!privateV4(host))||p<1024||p>65535){Toast.makeText(this,"请检查局域网地址、配对码和端口",Toast.LENGTH_LONG).show();return;}
            baseUrl=target.replaceAll("/+$","");token=code;manualHost=host;port=p;saveConfig();showMonitor();connectCamera();
        });root.addView(connect);setContentView(root);root.requestApplyInsets();
    }
    private boolean sameOrigin(Uri uri){
        if("about".equals(uri.getScheme()))return true;
        Uri allowed=Uri.parse(baseUrl);return allowed.getScheme().equals(uri.getScheme())&&allowed.getHost().equals(uri.getHost())&&allowed.getPort()==uri.getPort();
    }
    private WebView browser(boolean js){
        WebView view=new WebView(this);view.setBackgroundColor(0xffe1f5fe);view.getSettings().setJavaScriptEnabled(js);
        view.getSettings().setAllowFileAccess(false);view.getSettings().setAllowContentAccess(false);
        view.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return !sameOrigin(r.getUrl());}
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){return sameOrigin(r.getUrl())?null:new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));}
        });return view;
    }
    private void showMonitor(){
        clearViews();LinearLayout root=root(LinearLayout.HORIZONTAL);
        web=browser(true);root.addView(web,new LinearLayout.LayoutParams(0,-1,3));
        LinearLayout side=new LinearLayout(this);side.setOrientation(LinearLayout.VERTICAL);
        side.addView(text("台面 · DroidCam Wi-Fi",16));preview=browser(false);side.addView(preview,new LinearLayout.LayoutParams(-1,0,1));
        status=text("正在连接电脑与 DroidCam…",12);side.addView(status);
        Button launch=new Button(this);launch.setText("启动 / 设置 DroidCam");launch.setOnClickListener(v->launchDroidCam(false));side.addView(launch);
        Button connect=new Button(this);connect.setText("连接 Wi-Fi 摄像头");connect.setOnClickListener(v->connectCamera());side.addView(connect);
        Button stop=new Button(this);stop.setText("停止台面传输");stop.setOnClickListener(v->commandStop());side.addView(stop);
        Button settings=new Button(this);settings.setText("配对 / 网络设置");settings.setOnClickListener(v->showConnection());side.addView(settings);
        root.addView(side,new LinearLayout.LayoutParams(0,-1,1.2f));setContentView(root);root.requestApplyInsets();
        try{web.loadUrl(baseUrl+"/phone?token="+URLEncoder.encode(token,"UTF-8"));renderPreview();}catch(Exception ignored){}
    }
    private void renderPreview(){
        if(preview==null)return;
        try{String url=baseUrl+"/stream/desk.mjpg?view=live&token="+URLEncoder.encode(token,"UTF-8");
            preview.loadDataWithBaseURL(baseUrl+"/","<html><meta name='viewport' content='width=device-width,initial-scale=1'><body style='margin:0;background:#17213e;display:flex;align-items:center;height:100vh'><img style='width:100%;max-height:100%;object-fit:contain' src='"+url+"'></body></html>","text/html","UTF-8",null);
        }catch(Exception ignored){}
    }
    private void launchDroidCam(boolean returnWhenReady){
        if(!resumed)return;
        Intent intent=getPackageManager().getLaunchIntentForPackage("com.dev47apps.obsdroidcam");
        if(intent==null)intent=getPackageManager().getLaunchIntentForPackage("com.dev47apps.droidcam");
        if(intent==null){Toast.makeText(this,"请先安装官方 DroidCam 应用",Toast.LENGTH_LONG).show();return;}
        lastCameraLaunch=SystemClock.elapsedRealtime();returningFromCamera=returnWhenReady;returnDeadline=lastCameraLaunch+20000;
        if(returnWhenReady)intent.setFlags(0); // 与小屏保持同一前台任务，允许接通后切回小屏。
        startActivity(intent);Toast.makeText(this,returnWhenReady?"正在唤醒 DroidCam，接通后返回小屏；也可按返回键":"选择后置主摄，设置完成后返回小屏",Toast.LENGTH_LONG).show();
    }
    private String localCameraHost(){
        if(!manualHost.isEmpty())return manualHost;
        try{
            byte[] server=InetAddress.getByName(Uri.parse(baseUrl).getHost()).getAddress();
            Enumeration<NetworkInterface> networks=NetworkInterface.getNetworkInterfaces();
            String best="";int bestPrefix=-1;
            while(networks.hasMoreElements()){
                NetworkInterface network=networks.nextElement();String name=network.getName();
                if(!network.isUp()||network.isLoopback()||!(name.contains("wlan")||name.contains("ap")||name.contains("br")))continue;
                for(InterfaceAddress binding:network.getInterfaceAddresses()){
                    InetAddress candidate=binding.getAddress();if(!(candidate instanceof Inet4Address)||!privateV4(candidate.getHostAddress()))continue;
                    int prefix=binding.getNetworkPrefixLength();byte[] address=candidate.getAddress();boolean match=true;
                    for(int bit=0;bit<prefix;bit++)if(((server[bit/8]^address[bit/8])&(128>>(bit%8)))!=0){match=false;break;}
                    if(match&&prefix>bestPrefix){best=candidate.getHostAddress();bestPrefix=prefix;}
                }
            }return best;
        }catch(Exception e){return "";}
    }
    private void showStatus(String value){runOnUiThread(()->{if(status!=null)status.setText(value);});}
    private JSONObject api(String path,JSONObject body)throws Exception{
        HttpURLConnection connection=(HttpURLConnection)new URL(baseUrl+path).openConnection();
        try{
            connection.setConnectTimeout(2000);connection.setReadTimeout(5000);connection.setInstanceFollowRedirects(false);connection.setRequestProperty("X-Token",token);
            if(body!=null){byte[] bytes=body.toString().getBytes("UTF-8");connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");connection.setFixedLengthStreamingMode(bytes.length);try(java.io.OutputStream out=connection.getOutputStream()){out.write(bytes);}}
            int code=connection.getResponseCode();if(code!=200)throw new java.io.IOException(code==401?"配对码无效":"电脑返回 HTTP "+code);
            try(InputStream in=connection.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] bytes=new byte[4096];int n;while((n=in.read(bytes))!=-1){out.write(bytes,0,n);if(out.size()>262144)throw new java.io.IOException("响应过大");}return new JSONObject(out.toString("UTF-8"));
            }
        }finally{connection.disconnect();}
    }
    private void connectCamera(){
        if(status==null||!busy.compareAndSet(false,true))return;
        final String host=localCameraHost();if(host.isEmpty()){busy.set(false);showStatus("未找到同网段手机地址\n请连接手机热点，或在网络设置中填写 DroidCam IP。");return;}
        showStatus("正在接入 DroidCam："+host+":"+port);
        network.execute(()->{try{JSONObject result=api("/api/droidcam/connect",new JSONObject().put("host",host).put("port",port).put("rotation",0));showStatus("已提交连接，请保持 DroidCam 后台运行");
            JSONObject camera=result.optJSONObject("camera");if(camera!=null&&!camera.optBoolean("connected"))runOnUiThread(()->{if(SystemClock.elapsedRealtime()-lastCameraLaunch>15000)launchDroidCam(true);});
        }catch(Exception e){showStatus("Wi-Fi 连接失败："+e.getMessage());}finally{busy.set(false);}});
    }
    private void refreshStatus(){
        if(!busy.compareAndSet(false,true))return;
        network.execute(()->{try{JSONObject s=api("/api/droidcam",null);boolean live=s.optBoolean("connected"),enabled=s.optBoolean("enabled");
            showStatus((live?"DroidCam 已连接":enabled?"等待 DroidCam":"台面传输已停止")+" · "+s.optString("host")+":"+s.optInt("port",4747)+"\nWi-Fi 实收 "+s.optDouble("received_fps",0)+" / 24 帧/秒"+(live?"":enabled?"\n"+s.optString("error","打开 DroidCam 后返回小屏"):"\n点击连接可恢复"));
            if(live&&returningFromCamera){returningFromCamera=false;runOnUiThread(()->{if(!resumed){Intent back=new Intent(this,MainActivity.class);back.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT|Intent.FLAG_ACTIVITY_SINGLE_TOP);startActivity(back);}});}
            else if(!live&&enabled&&!s.optString("error").isEmpty())runOnUiThread(()->{if(resumed&&SystemClock.elapsedRealtime()-lastCameraLaunch>30000)launchDroidCam(true);});
        }catch(Exception e){showStatus("电脑未连接："+e.getMessage()+"\n请检查热点、电脑地址及配对码。");}finally{busy.set(false);}});
    }
    private void commandStop(){
        if(!busy.compareAndSet(false,true))return;
        network.execute(()->{try{api("/api/droidcam/disconnect",new JSONObject());showStatus("台面传输已停止，点击连接可恢复");}catch(Exception e){showStatus("停止失败："+e.getMessage());}finally{busy.set(false);}});
    }
    @Override protected void onResume(){super.onResume();resumed=true;if(web!=null)web.onResume();if(preview!=null){preview.onResume();renderPreview();}if(status!=null)connectCamera();}
    @Override protected void onPause(){resumed=false;if(web!=null)web.onPause();if(preview!=null){preview.stopLoading();preview.loadUrl("about:blank");preview.onPause();}super.onPause();}
    @Override protected void onDestroy(){handler.removeCallbacks(poll);clearViews();network.shutdownNow();super.onDestroy();}
}

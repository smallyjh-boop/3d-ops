# 网页里调用的原生方法（window.Android3D.xxx）不能被混淆 / 删掉
-keepclassmembers class com.threedops.app.WebBridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface

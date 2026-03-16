var CHARS = "01ABCDEF0110><{}[]";
var i, j, k;

/* ── FILE INPUT DISPLAY ── */
document.getElementById("uploadInput").addEventListener("change", function() {
  var n = this.files && this.files[0] ? this.files[0].name : "No file chosen";
  document.getElementById("fileNameDisplay").textContent = n;
  if (this.files && this.files[0]) { handleFile(this.files[0]); }
});

/* ── BACKGROUND MATRIX ── */
var bgC = document.getElementById("bg-layer");
var bgX = bgC.getContext("2d");
var BW = 0, BH = 0, drops = [], scanY = 0, glitches = [];

function mkG() {
  return {
    y: Math.random()*800, h: Math.random()*8+1,
    w: Math.random()*0.7+0.15, x: Math.random()*0.4,
    life: Math.random()*20+3, age: 0,
    shift: (Math.random()-0.5)*30,
    alpha: Math.random()*0.55+0.2,
    r: Math.random()>0.85?150:0,
    b: Math.random()>0.85?150:65
  };
}
for (i=0;i<22;i++) { glitches.push(mkG()); }

function resizeBg() {
  BW = bgC.width  = window.innerWidth;
  BH = bgC.height = window.innerHeight;
  drops = [];
  for (i=0;i<Math.floor(BW/15);i++) { drops.push(Math.floor(Math.random()*-50)); }
}
resizeBg();
window.addEventListener("resize", resizeBg);

function bgFrame() {
  bgX.fillStyle = "rgba(0,3,0,0.13)";
  bgX.fillRect(0,0,BW,BH);
  bgX.font = "13px 'Share Tech Mono',monospace";
  for (i=0;i<drops.length;i++) {
    var ch = CHARS[Math.floor(Math.random()*CHARS.length)];
    var b  = Math.random();
    bgX.fillStyle = b>0.96?"#ccffcc":b>0.55?"#00ff41":b>0.28?"#006622":"#002e10";
    bgX.fillText(ch, i*15, drops[i]*15);
    if (drops[i]*15>BH && Math.random()>0.975) { drops[i]=0; }
    drops[i]++;
  }
  bgX.fillStyle = "rgba(0,255,65,0.045)";
  bgX.fillRect(0,scanY,BW,3);
  scanY = (scanY+1.5)%BH;
  for (i=0;i<glitches.length;i++) {
    var g = glitches[i];
    g.age++;
    var fa = g.alpha*(1-g.age/g.life);
    var gx = g.x*BW+g.shift*(g.age/g.life);
    var gw = g.w*BW;
    bgX.fillStyle = "rgba("+g.r+",255,"+g.b+","+fa+")";
    bgX.fillRect(gx,g.y,gw,g.h);
    if (g.h>5) {
      bgX.font = Math.floor(g.h*0.9+5)+"px 'Share Tech Mono',monospace";
      var txt="";
      for (k=0;k<Math.floor(gw/9);k++) { txt+=CHARS[Math.floor(Math.random()*CHARS.length)]; }
      bgX.fillStyle = "rgba(0,255,65,"+fa+")";
      bgX.fillText(txt,gx,g.y+g.h);
      bgX.font = "13px 'Share Tech Mono',monospace";
    }
    if (g.age>=g.life) { glitches[i]=mkG(); glitches[i].y=Math.random()*BH; }
  }
  requestAnimationFrame(bgFrame);
}
bgFrame();

/* ── INTERCEPT TEXT ── */
var ovl = document.getElementById("intercept-overlay");
var iLines = [
  "SYS UPLINK BREACH 0xA3F2CC",
  "RECV 01001000 01000101",
  "AUTH FAIL retrying 3 of 5",
  "TRACE ROUTE UNKNOWN HOST",
  "DECRYPT KEY CORRUPTED",
  "INJECTING PAYLOAD SCAN OVERRIDE",
  "SIGNAL LOCK LOST SCANNING",
  "XENO PROTOCOL v2.1 ACTIVE",
  "ANOMALY DETECTED SECTOR 7G",
  "FIREWALL BYPASS SUCCESS",
  "SCANNING LIFEFORMS 1 DETECTED",
  "DISTRESS BEACON ACTIVE",
  "OVERRIDE CODE 7734 ALPHA 9",
  "NULL POINTER 0x0000DEAD",
  "XENOMORPH SIGNAL CONFIRMED",
  "HULL BREACH SECTOR 4"
];
var iActive = [];

function spawnI() {
  if (iActive.length>8) { return; }
  var el = document.createElement("div");
  el.className = "intercept-block";
  var line = iLines[Math.floor(Math.random()*iLines.length)];
  el.textContent = line;
  el.style.top  = (Math.random()*88)+"%";
  el.style.left = (Math.random()*62)+"%";
  el.style.opacity = (Math.random()*0.5+0.3).toString();
  ovl.appendChild(el);
  iActive.push(el);
  var ticks=0;
  var ct = setInterval(function() {
    if (Math.random()>0.5) {
      var arr=line.split("");
      for (var n=0;n<arr.length;n++) {
        if (Math.random()>0.8) { arr[n]=CHARS[Math.floor(Math.random()*CHARS.length)]; }
      }
      el.textContent=arr.join("");
    }
    ticks++;
    if (ticks>18) { clearInterval(ct); el.textContent=line; }
  }, 80);
  setTimeout(function() {
    el.style.transition="opacity 0.4s";
    el.style.opacity="0";
    setTimeout(function() {
      if (el.parentNode) { el.parentNode.removeChild(el); }
      var idx=iActive.indexOf(el);
      if (idx>-1) { iActive.splice(idx,1); }
    }, 400);
  }, Math.random()*2500+800);
}
setInterval(function() { if (Math.random()>0.3) { spawnI(); } }, 600);

/* ── ALIEN BUTTONS ── */
function initBtn(btn) {
  var cnv  = btn.querySelector(".btn-canvas");
  var bCtx = cnv.getContext("2d");
  var lbl  = btn.querySelector(".btn-label");
  var orig = lbl.textContent;
  var aId=null, iId=null, hov=false, gp=0;

  function sz() { cnv.width=btn.offsetWidth; cnv.height=btn.offsetHeight; }
  sz();
  window.addEventListener("resize",sz);

  function drawIdle() {
    var w=cnv.width, h=cnv.height;
    bCtx.clearRect(0,0,w,h);
    gp+=0.04;
    var gv=Math.floor((Math.sin(gp)*0.5+0.5)*30+5);
    bCtx.fillStyle="rgba(0,"+gv+",0,0.4)";
    bCtx.fillRect(0,0,w,h);
    bCtx.font="9px 'Share Tech Mono',monospace";
    for (var n=0;n<6;n++) {
      if (Math.random()>0.6) {
        bCtx.fillStyle="rgba(0,255,65,"+(Math.random()*0.15)+")";
        bCtx.fillText(CHARS[Math.floor(Math.random()*CHARS.length)],Math.random()*w,Math.random()*h);
      }
    }
    if (Math.random()>0.92) {
      bCtx.fillStyle="rgba(0,255,65,"+(Math.random()*0.12+0.04)+")";
      bCtx.fillRect(0,Math.random()*h,w*Math.random(),Math.random()*2+1);
    }
    iId=requestAnimationFrame(drawIdle);
  }
  drawIdle();

  function drawGlitch() {
    if (!hov) { aId=null; return; }
    var w=cnv.width, h=cnv.height;
    bCtx.clearRect(0,0,w,h);
    gp+=0.12;
    bCtx.fillStyle="rgba(0,"+Math.floor(Math.random()*20)+",0,0.85)";
    bCtx.fillRect(0,0,w,h);
    bCtx.font="9px 'Share Tech Mono',monospace";
    var cols=Math.floor(w/9);
    for (var c=0;c<cols;c++) {
      for (var r=0;r<Math.floor(h/11);r++) {
        var a=Math.random();
        if      (a>0.9) { bCtx.fillStyle="rgba(200,255,200,"+(Math.random()*0.9+0.1)+")"; }
        else if (a>0.5) { bCtx.fillStyle="rgba(0,255,65,"+(Math.random()*0.7+0.1)+")"; }
        else             { bCtx.fillStyle="rgba(0,120,30,"+(Math.random()*0.3)+")"; }
        bCtx.fillText(CHARS[Math.floor(Math.random()*CHARS.length)],c*9,r*11+10);
      }
    }
    if (Math.random()>0.7) {
      var arr=orig.split("");
      for (var n=0;n<arr.length;n++) {
        if (Math.random()>0.75) { arr[n]=CHARS[Math.floor(Math.random()*CHARS.length)]; }
      }
      lbl.textContent=arr.join("");
      setTimeout(function(){ lbl.textContent=orig; }, 80);
    }
    aId=requestAnimationFrame(drawGlitch);
  }

  btn.addEventListener("mouseenter",function(){ hov=true; cancelAnimationFrame(iId); iId=null; if(!aId){drawGlitch();} });
  btn.addEventListener("mouseleave",function(){ hov=false; lbl.textContent=orig; cancelAnimationFrame(aId); aId=null; drawIdle(); });
}

var btns=document.querySelectorAll(".alien-btn");
for (i=0;i<btns.length;i++) { initBtn(btns[i]); }

/* ── 3D VIEWER ── */
setTimeout(function() {
  var canvas    = document.getElementById("viewer-canvas");
  var dropZone  = document.getElementById("viewer-drop-zone");
  var loadBar   = document.getElementById("viewer-loading");
  var errorMsg  = document.getElementById("viewer-error");
  var hudTL     = document.getElementById("hud-tl");
  var hudBR     = document.getElementById("hud-br");
  var container = document.getElementById("viewerArea");

  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;

  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000300);
  scene.fog = new THREE.Fog(0x000300, 10, 80);

  var camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1000);
  camera.position.set(0, 2, 5);

  var ambientLight = new THREE.AmbientLight(0x00ff41, 0.3);
  scene.add(ambientLight);

  var dirLight = new THREE.DirectionalLight(0x00ff88, 1.2);
  dirLight.position.set(5, 10, 5);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width  = 2048;
  dirLight.shadow.mapSize.height = 2048;
  scene.add(dirLight);

  var fillLight = new THREE.DirectionalLight(0x004422, 0.5);
  fillLight.position.set(-5, -2, -5);
  scene.add(fillLight);

  var pointLight1 = new THREE.PointLight(0x00ff41, 0.8, 30);
  pointLight1.position.set(-3, 4, 3);
  scene.add(pointLight1);

  var pointLight2 = new THREE.PointLight(0x00ffcc, 0.5, 20);
  pointLight2.position.set(3, 2, -3);
  scene.add(pointLight2);

  var gridHelper = new THREE.GridHelper(30, 30, 0x00ff41, 0x003311);
  gridHelper.material.opacity = 0.3;
  gridHelper.material.transparent = true;
  scene.add(gridHelper);

  function resizeViewer() {
    var w = container.clientWidth;
    var h = container.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resizeViewer();
  window.addEventListener("resize", resizeViewer);

  var orb = {
    dragging:  false,
    rightDrag: false,
    lastX: 0, lastY: 0,
    theta: 0.3, phi: 1.1,
    radius: 5,
    target: new THREE.Vector3(0,0,0)
  };

  function updateCam() {
    var x = orb.target.x + orb.radius * Math.sin(orb.phi) * Math.sin(orb.theta);
    var y = orb.target.y + orb.radius * Math.cos(orb.phi);
    var z = orb.target.z + orb.radius * Math.sin(orb.phi) * Math.cos(orb.theta);
    camera.position.set(x, y, z);
    camera.lookAt(orb.target);
  }
  updateCam();

  canvas.addEventListener("mousedown", function(e) {
    if (e.button === 2) { orb.rightDrag = true; }
    else                { orb.dragging  = true; }
    orb.lastX = e.clientX;
    orb.lastY = e.clientY;
    e.preventDefault();
  });
  canvas.addEventListener("contextmenu", function(e) { e.preventDefault(); });
  window.addEventListener("mouseup", function() { orb.dragging=false; orb.rightDrag=false; });
  window.addEventListener("mousemove", function(e) {
    var dx = e.clientX - orb.lastX;
    var dy = e.clientY - orb.lastY;
    orb.lastX = e.clientX;
    orb.lastY = e.clientY;
    if (orb.dragging) {
      orb.theta -= dx * 0.008;
      orb.phi   -= dy * 0.008;
      orb.phi    = Math.max(0.05, Math.min(Math.PI-0.05, orb.phi));
      updateCam();
    }
    if (orb.rightDrag) {
      var ps = orb.radius * 0.001;
      var right = new THREE.Vector3();
      right.crossVectors(camera.getWorldDirection(new THREE.Vector3()), camera.up).normalize();
      orb.target.addScaledVector(right, -dx*ps);
      orb.target.addScaledVector(camera.up, dy*ps);
      updateCam();
    }
  });
  canvas.addEventListener("wheel", function(e) {
    e.preventDefault();
    orb.radius = Math.max(0.5, Math.min(50, orb.radius + e.deltaY*0.01));
    updateCam();
  }, { passive: false });

  var lastTD = 0;
  canvas.addEventListener("touchstart", function(e) {
    if (e.touches.length===1) {
      orb.dragging=true; orb.lastX=e.touches[0].clientX; orb.lastY=e.touches[0].clientY;
    } else if (e.touches.length===2) {
      orb.dragging=false;
      lastTD=Math.hypot(e.touches[0].clientX-e.touches[1].clientX, e.touches[0].clientY-e.touches[1].clientY);
    }
    e.preventDefault();
  }, { passive: false });
  window.addEventListener("touchend", function() { orb.dragging=false; });
  window.addEventListener("touchmove", function(e) {
    if (orb.dragging && e.touches.length===1) {
      var dx=e.touches[0].clientX-orb.lastX, dy=e.touches[0].clientY-orb.lastY;
      orb.lastX=e.touches[0].clientX; orb.lastY=e.touches[0].clientY;
      orb.theta-=dx*0.008; orb.phi-=dy*0.008;
      orb.phi=Math.max(0.05,Math.min(Math.PI-0.05,orb.phi));
      updateCam();
    } else if (e.touches.length===2) {
      var d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX, e.touches[0].clientY-e.touches[1].clientY);
      orb.radius=Math.max(0.5,Math.min(50,orb.radius-(d-lastTD)*0.02));
      lastTD=d; updateCam();
    }
  });

  var currentModel = null;

  function clearModel() {
    if (currentModel) {
      scene.remove(currentModel);
      currentModel.traverse(function(obj) {
        if (obj.geometry) { obj.geometry.dispose(); }
        if (obj.material) {
          if (Array.isArray(obj.material)) {
            obj.material.forEach(function(m) { m.dispose(); });
          } else { obj.material.dispose(); }
        }
      });
      currentModel = null;
    }
  }

  function fitCamera(object) {
    var box    = new THREE.Box3().setFromObject(object);
    var center = box.getCenter(new THREE.Vector3());
    var size   = box.getSize(new THREE.Vector3());
    var maxDim = Math.max(size.x, size.y, size.z);
    var fov    = camera.fov * (Math.PI / 180);
    orb.radius = Math.abs(maxDim / Math.sin(fov/2)) * 0.8;
    orb.target.copy(center);
    orb.phi=1.1; orb.theta=0.3;
    updateCam();
  }

  function applyMaterial(object) {
    object.traverse(function(child) {
      if (child.isMesh) {
        child.castShadow    = true;
        child.receiveShadow = true;
        if (!child.material || child.material.name === "") {
          child.material = new THREE.MeshStandardMaterial({
            color:     0x00cc44,
            emissive:  0x002200,
            roughness: 0.6,
            metalness: 0.2
          });
        }
      }
    });
  }

  function countPolys(model) {
    var polys = 0;
    model.traverse(function(c) {
      if (c.isMesh) {
        if (c.geometry.index) { polys += c.geometry.index.count / 3; }
        else if (c.geometry.attributes.position) { polys += c.geometry.attributes.position.count / 3; }
      }
    });
    return Math.floor(polys);
  }

  function updateHUD(name, polys, size) {
    hudTL.innerHTML =
      "&gt; SCAN VIEWER v2.0<br>" +
      "&gt; FILE: " + name + "<br>" +
      "&gt; STATUS: LOADED";
    hudBR.textContent =
      "POLYS: " + polys + " | " +
      size.x.toFixed(1) + "x" + size.y.toFixed(1) + "x" + size.z.toFixed(1) + "m";
  }

  function setLoad(pct) {
    if (pct === null) { loadBar.style.display="none"; loadBar.style.width="0%"; }
    else { loadBar.style.display="block"; loadBar.style.width=pct+"%"; }
  }

  function showErr(msg) {
    errorMsg.textContent = msg;
    errorMsg.style.display = "block";
    setTimeout(function() { errorMsg.style.display="none"; }, 5000);
  }

  function onModelLoaded(model, name) {
    setLoad(90);
    clearModel();
    applyMaterial(model);
    scene.add(model);
    currentModel = model;
    fitCamera(model);
    var box  = new THREE.Box3().setFromObject(model);
    var size = box.getSize(new THREE.Vector3());
    updateHUD(name, countPolys(model), size);
    dropZone.style.display = "none";
    setLoad(null);
    document.getElementById("statusBox").textContent = "LOADED: " + name;
  }

  function loadGLTFLoader(cb) {
    if (THREE.GLTFLoader) { cb(); return; }
    var s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js";
    s.onload = cb;
    document.head.appendChild(s);
  }

  function loadOBJLoader(cb) {
    if (THREE.OBJLoader) { cb(); return; }
    var s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/OBJLoader.js";
    s.onload = cb;
    document.head.appendChild(s);
  }

  function loadGLB(url, name) {
    setLoad(10);
    loadGLTFLoader(function() {
      var loader = new THREE.GLTFLoader();
      loader.load(url,
        function(gltf) { onModelLoaded(gltf.scene, name); },
        function(xhr)  { if (xhr.total>0) { setLoad(Math.floor((xhr.loaded/xhr.total)*80)+10); } },
        function(err)  { setLoad(null); showErr("ERROR: " + err.message); }
      );
    });
  }

  function loadOBJ(url, name) {
    setLoad(10);
    loadOBJLoader(function() {
      var loader = new THREE.OBJLoader();
      loader.load(url,
        function(obj)  { onModelLoaded(obj, name); },
        function(xhr)  { if (xhr.total>0) { setLoad(Math.floor((xhr.loaded/xhr.total)*80)+10); } },
        function(err)  { setLoad(null); showErr("ERROR: " + err.message); }
      );
    });
  }

  function handleFile(file) {
    var ext  = file.name.split(".").pop().toLowerCase();
    var url  = URL.createObjectURL(file);
    var name = file.name.toUpperCase();
    errorMsg.style.display = "none";
    hudTL.innerHTML = "&gt; SCAN VIEWER v2.0<br>&gt; FILE: "+name+"<br>&gt; STATUS: LOADING...";
    if (ext==="glb"||ext==="gltf") { loadGLB(url, name); }
    else if (ext==="obj")          { loadOBJ(url, name); }
    else { showErr("UNSUPPORTED: ."+ext.toUpperCase()+" -- USE .GLB OR .OBJ"); }
  }

  window.handleFile = handleFile;

  container.addEventListener("dragover", function(e) {
    e.preventDefault();
    container.style.borderColor = "#aaffaa";
  });
  container.addEventListener("dragleave", function() {
    container.style.borderColor = "#00ff41";
  });
  container.addEventListener("drop", function(e) {
    e.preventDefault();
    container.style.borderColor = "#00ff41";
    var file = e.dataTransfer.files[0];
    if (file) { handleFile(file); }
  });

  window.addEventListener("keydown", function(e) {
    if (e.key==="r"||e.key==="R") {
      orb.theta=0.3; orb.phi=1.1; orb.target.set(0,0,0);
      if (currentModel) { fitCamera(currentModel); }
      else { orb.radius=5; updateCam(); }
    }
    if ((e.key==="w"||e.key==="W") && currentModel) {
      currentModel.traverse(function(c) {
        if (c.isMesh && c.material) { c.material.wireframe = !c.material.wireframe; }
      });
    }
    if (e.key==="g"||e.key==="G") { gridHelper.visible = !gridHelper.visible; }
  });

  document.getElementById("clearButton").addEventListener("click", function() {
    clearModel();
    dropZone.style.display = "block";
    hudTL.innerHTML = "&gt; SCAN VIEWER v2.0<br>&gt; ENGINE: THREE.JS<br>&gt; STATUS: READY";
    hudBR.textContent = "NO MODEL LOADED";
    document.getElementById("statusBox").textContent = "No activity yet.";
    document.getElementById("fileNameDisplay").textContent = "No file chosen";
  });

  var vtick = 0;
  function animate() {
    requestAnimationFrame(animate);
    vtick++;
    pointLight1.intensity = 0.6 + Math.sin(vtick*0.02)*0.2;
    pointLight2.intensity = 0.4 + Math.sin(vtick*0.03+1)*0.15;
    if (!orb.dragging && !orb.rightDrag && currentModel) {
      orb.theta += 0.002;
      updateCam();
    }
    renderer.render(scene, camera);
  }
  animate();

}, 500);
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

/** Orbit viewer for a GLB display mesh. The mesh is for looking only; every
 *  measurement in the app comes from the exact B-rep solid on the server. */
export default function ModelViewer({ url, label }: { url: string; label?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let disposed = false;
    const width = element.clientWidth || 600;
    const height = element.clientHeight || 380;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setError("3D preview needs WebGL, which this browser has disabled.");
      setLoading(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    element.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.0001, 100);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.4));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 2, 1.5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-1.5, 0.5, -1);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };

    new GLTFLoader().load(
      url,
      (gltf) => {
        if (disposed) return;
        const model = gltf.scene;
        model.traverse((child) => {
          const mesh = child as THREE.Mesh;
          if (mesh.isMesh) {
            const material = mesh.material as THREE.MeshStandardMaterial;
            material.metalness = 0.15;
            material.roughness = 0.55;
            material.side = THREE.DoubleSide;
            const edges = new THREE.LineSegments(
              new THREE.EdgesGeometry(mesh.geometry, 25),
              new THREE.LineBasicMaterial({ color: 0x2b3a4f, transparent: true, opacity: 0.55 }),
            );
            mesh.add(edges);
          }
        });
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const radius = Math.max(size.x, size.y, size.z) || 0.1;
        const grid = new THREE.GridHelper(radius * 3, 12, 0x8796aa, 0xc5cfdb);
        grid.position.set(center.x, box.min.y - radius * 0.002, center.z);
        scene.add(grid);
        camera.position.set(center.x + radius * 1.4, center.y + radius * 1.1, center.z + radius * 1.6);
        camera.near = radius / 1000;
        camera.far = radius * 100;
        camera.updateProjectionMatrix();
        controls.target.copy(center);
        controls.update();
        setLoading(false);
        animate();
      },
      undefined,
      () => {
        if (!disposed) {
          setError("Could not load the 3D preview.");
          setLoading(false);
        }
      },
    );

    const resize = () => {
      const w = element.clientWidth;
      const h = element.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((m) => m.dispose());
        else material?.dispose?.();
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return (
    <div className="viewer" ref={host}>
      {(loading || error) && (
        <div className="center-page" style={{ position: "absolute", inset: 0, minHeight: 0 }}>
          <span className="muted">{error ?? "Loading 3D preview…"}</span>
        </div>
      )}
      <div className="overlay">{label ?? "Drag to orbit · scroll to zoom · display mesh only"}</div>
    </div>
  );
}

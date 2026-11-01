import { env, pipeline, type FeatureExtractionPipeline } from '@huggingface/transformers';

export type Device = 'webgpu' | 'wasm';
export type Dtype = 'q8' | 'fp16' | 'fp32';

export interface LoadOptions {
  modelId: string;
  device: Device;
  dtype: Dtype;
  host?: string;
  onProgress?: (ratio: number, label: string) => void;
}

export interface EmbedResult {
  vectors: number[][];
  ms: number;
}

interface GpuAdapterInfo {
  vendor?: string;
  architecture?: string;
  device?: string;
  description?: string;
}

interface GpuAdapter {
  requestAdapterInfo?: () => Promise<GpuAdapterInfo>;
}

interface GpuLike {
  requestAdapter: () => Promise<GpuAdapter | null>;
}

interface ProgressEvent {
  status?: string;
  progress?: number;
  file?: string;
}

type PipelineLoader = (
  task: 'feature-extraction',
  model: string,
  options: Record<string, unknown>,
) => Promise<FeatureExtractionPipeline>;

const gpuApi = (): GpuLike | undefined => {
  if (typeof navigator === 'undefined') {
    return undefined;
  }
  const candidate = (navigator as unknown as { gpu?: GpuLike }).gpu;
  return candidate && typeof candidate.requestAdapter === 'function' ? candidate : undefined;
};

export async function detectDevice(): Promise<Device> {
  const gpu = gpuApi();
  if (!gpu) {
    return 'wasm';
  }
  try {
    const adapter = await gpu.requestAdapter();
    return adapter ? 'webgpu' : 'wasm';
  } catch {
    return 'wasm';
  }
}

export const gpuDescription = async (): Promise<string> => {
  const gpu = gpuApi();
  if (!gpu) {
    return 'WebGPU 不可用';
  }
  try {
    const adapter = await gpu.requestAdapter();
    const info = adapter?.requestAdapterInfo ? await adapter.requestAdapterInfo() : null;
    return info?.description || info?.vendor || 'WebGPU 可用';
  } catch {
    return 'WebGPU 可用';
  }
};

export class BrowserEmbedder {
  private extractor: FeatureExtractionPipeline | null = null;

  readonly dimension = 384;

  get ready(): boolean {
    return this.extractor !== null;
  }

  async load(options: LoadOptions): Promise<number> {
    const started = performance.now();
    env.allowLocalModels = false;
    env.useBrowserCache = true;
    if (options.host) {
      env.remoteHost = options.host;
      env.remotePathTemplate = '{model}/resolve/{revision}/';
    }
    const loader = pipeline as unknown as PipelineLoader;
    this.extractor = await loader('feature-extraction', options.modelId, {
      device: options.device,
      dtype: options.dtype,
      progress_callback: (event: ProgressEvent) => {
        if (!options.onProgress) {
          return;
        }
        const ratio = typeof event.progress === 'number' ? Math.min(event.progress, 1) : 0;
        const label = event.status === 'progress' ? (event.file ?? '下载模型') : (event.status ?? '初始化');
        options.onProgress(ratio, label);
      },
    });
    await this.embed(['warm up']);
    return performance.now() - started;
  }

  async embed(texts: string[]): Promise<EmbedResult> {
    if (!this.extractor) {
      throw new Error('embedding model is not loaded');
    }
    const started = performance.now();
    const vectors: number[][] = [];
    for (const text of texts) {
      const output = await this.extractor([text], { pooling: 'mean', normalize: true });
      const [vector] = output.tolist() as number[][];
      vectors.push(vector);
    }
    return { vectors, ms: performance.now() - started };
  }

  async dispose(): Promise<void> {
    await this.extractor?.dispose();
    this.extractor = null;
  }
}
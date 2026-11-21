import { defineConfig } from 'astro/config';

export default defineConfig({
  // 第一阶段以静态生成为主，后续需要时再增加 SSR 适配器。
  output: 'static'
});

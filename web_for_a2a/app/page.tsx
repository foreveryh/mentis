'use client';

import Link from 'next/link';

export default function Home() {
  return (
    <div className="container mx-auto p-8">
      <h1 className="text-3xl font-bold mb-6">DeepResearch A2A Web 客户端</h1>
      
      <div className="bg-white shadow-md rounded-lg p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">功能介绍</h2>
        <p className="mb-4">
          这是一个基于 Next.js 和 React 构建的 Web 客户端，用于连接 DeepResearch A2A 服务器并展示流式研究结果。
          通过 Server-Sent Events (SSE) 技术，可以实时接收和显示研究进度和最终报告。
        </p>
        <p className="mb-4">
          本示例演示了如何从前端 Web 应用连接到 DeepResearch A2A 服务器 (<code>tasks/sendSubscribe</code> 端点)，
          并接收、解析、显示 SSE 流。
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">使用前提</h2>
        <ul className="list-disc pl-6 space-y-2">
          <li>
            确保 <code>super_agents/deep_research/a2a_adapter/run_server.py</code> 启动的服务器正在运行在 
            <code>http://127.0.0.1:8000</code> (或相应的地址)。
          </li>
          <li>
            当前示例使用硬编码的研究主题 "特斯拉电动汽车的市场分析和未来发展趋势"。
          </li>
        </ul>
      </div>

      <Link 
        href="/deepresearch" 
        className="inline-block px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
      >
        进入 DeepResearch 示例页面
      </Link>
    </div>
  );
}
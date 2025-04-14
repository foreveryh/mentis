// 文件路径: app/api/a2a/[[...slug]]/route.ts (适用于 App Router)
// 或 pages/api/a2a/[...slug].ts (适用于 Pages Router, 需 slight modification in handler signature)

import { type NextRequest, NextResponse } from 'next/server';
import { NextApiRequest, NextApiResponse } from 'next'; // For Pages Router

// 后端 A2A 服务器的地址
const A2A_BACKEND_URL = process.env.A2A_BACKEND_URL || 'http://127.0.0.1:8000';

// --- App Router Version ---
export async function POST(request: NextRequest) {
  try {
    // 1. 获取前端请求的 body
    const body = await request.json();
    console.log('[API Route] Forwarding POST request to:', A2A_BACKEND_URL);
    console.log('[API Route] Request Body:', JSON.stringify(body, null, 2));

    // 2. 构造转发到 A2A 后端的请求
    // 注意： NextRequest.headers 是 Headers 对象, fetch 也接受 Headers 对象
    // 我们需要筛选或传递合适的 Headers
    const headersToForward = new Headers();
    headersToForward.set('Content-Type', 'application/json');
    // 如果后端需要 Accept 头来决定是否返回 SSE
    if (body?.method === 'tasks/sendSubscribe') {
        headersToForward.set('Accept', 'text/event-stream');
    } else {
         headersToForward.set('Accept', 'application/json');
    }
    // 你可能需要传递其他必要的头，例如 Authorization (如果需要的话)
    // const authHeader = request.headers.get('Authorization');
    // if (authHeader) headersToForward.set('Authorization', authHeader);


    // 3. 使用 fetch 将请求转发到后端 A2A 服务器
    const backendResponse = await fetch(A2A_BACKEND_URL, {
      method: 'POST',
      headers: headersToForward,
      body: JSON.stringify(body),
      // 重要：如果需要流式传输，Node fetch 需要 duplex:'half' (或者它默认支持流)
      // 对于 Vercel Edge Runtime (默认在 App Router API Routes 中)， fetch 原生支持流
      // cache: 'no-store', // 确保不缓存
    });

    console.log(`[API Route] Backend response status: ${backendResponse.status}`);
    backendResponse.headers.forEach((value, key) => console.log(`[API Route] Backend header: ${key}: ${value}`));


    // 4. 处理后端响应
    const contentType = backendResponse.headers.get('content-type');

    if (contentType?.includes('text/event-stream') && backendResponse.body) {
      // 4a. 如果是 SSE 流，将其转发给前端
      console.log('[API Route] Forwarding SSE stream...');
      // 创建一个新的 ReadableStream 将后端流转发给前端
      const stream = new ReadableStream({
        async start(controller) {
          const reader = backendResponse.body!.getReader();
          const decoder = new TextDecoder(); // 用于调试日志
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                console.log('[API Route] Backend stream ended.');
                controller.close();
                break;
              }
              const decodedChunk = decoder.decode(value); // 调试用
              console.log('[API Route] Forwarding stream chunk:', decodedChunk.replace(/\n/g, '\\n'));
              controller.enqueue(value); // 将原始 Uint8Array 块转发给前端
            }
          } catch (error) {
            console.error('[API Route] Error reading from backend stream:', error);
            controller.error(error);
          } finally {
             // 确保 reader 被释放 (尽管在 done=true 或 error 时通常会自动处理)
            try {
                reader.releaseLock();
            } catch {}
          }
        }
      });

      // 返回带有正确 SSE 头信息的流式响应
      return new Response(stream, {
        status: backendResponse.status,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          // 可以选择性地转发其他必要的后端头信息
        }
      });

    } else {
      // 4b. 如果是普通 JSON 响应，解析并转发
      console.log('[API Route] Forwarding JSON response...');
      const jsonResponse = await backendResponse.json();
      console.log('[API Route] Backend JSON:', jsonResponse);
      return NextResponse.json(jsonResponse, { status: backendResponse.status });
    }

  } catch (error: any) {
    console.error("[API Route] Error in proxy:", error);
    return NextResponse.json(
        { error: 'Proxy error', detail: error.message },
        { status: 500 }
    );
  }
}

// 可以选择性地添加 GET 处理 /.well-known/agent.json (如果前端也想通过代理获取)
export async function GET(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === '/api/a2a/.well-known/agent.json') {
     try {
         const backendResponse = await fetch(`${A2A_BACKEND_URL}/.well-known/agent.json`);
         if (!backendResponse.ok) { throw new Error(`Backend error: ${backendResponse.status}`)};
         const data = await backendResponse.json();
         return NextResponse.json(data);
     } catch (error: any) {
         console.error("[API Route] Error fetching agent card:", error);
         return NextResponse.json({ error: 'Failed to fetch agent card'}, { status: 502 });
     }
  }
   return NextResponse.json({ error: 'Not Found' }, { status: 404 });
}

// --- Pages Router Version (Alternative) ---
/*
import type { NextApiRequest, NextApiResponse } from 'next';
import httpProxyMiddleware from 'next-http-proxy-middleware'; // 需要安装 next-http-proxy-middleware

const A2A_BACKEND_URL = process.env.A2A_BACKEND_URL || 'http://127.0.0.1:8000';

export const config = {
  api: {
    // 关闭 Next.js 的默认 body 解析，让代理处理
    bodyParser: false,
  },
};

// 使用 next-http-proxy-middleware 处理代理 (更简单，但流式支持可能需要验证)
const handler = (req: NextApiRequest, res: NextApiResponse) => {
    console.log(`[API Route Pages] Forwarding request ${req.method} ${req.url} to ${A2A_BACKEND_URL}`);
    return httpProxyMiddleware(req, res, {
        target: A2A_BACKEND_URL,
        // 重写路径，移除 /api/a2a 前缀
        pathRewrite: [{
            patternStr: '^/api/a2a',
            replaceStr: '',
        }],
        // 可能需要配置 changeOrigin: true
        changeOrigin: true,
        // selfHandleResponse: true, // 可能需要手动处理流式响应头，如果库不支持
        // onProxyRes: (proxyRes, req, res) => {
        //    // 如果需要手动处理 SSE 头
        //   if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
        //     res.setHeader('Content-Type', 'text/event-stream');
        //     res.setHeader('Cache-Control', 'no-cache');
        //     res.setHeader('Connection', 'keep-alive');
        //     // 可能需要移除或修改其他头
        //   }
        // }
    });
};

export default handler;
*/
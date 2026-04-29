import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);

function App() {
  const [count, setCount] = useState(0);

  return html`
    <div
      class="p-8 bg-white rounded-xl shadow-lg text-center border border-gray-200"
    >
      <h1 class="text-3xl font-bold text-blue-600 mb-4">React + Tailwind</h1>
      <p class="text-gray-600 mb-6">
        No Vite, no build step, just pure CDN power.
      </p>

      <button
        onClick=${() => setCount(count + 1)}
        class="px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-lg transition-colors duration-200 shadow-md"
      >
        Count is: ${count}
      </button>
    </div>
  `;
}

const root = createRoot(document.getElementById("root"));
root.render(html`<${App} />`);

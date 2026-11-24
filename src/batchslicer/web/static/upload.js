// Uploads for the BatchSlicer page: drag files, zip files or folders onto the
// drop area, or choose them. Every file is sent in one request with its path
// (so folders keep their shape); the server puts them into the watched folder
// once all have arrived. The page's token goes with it, as the server requires.
(() => {
  "use strict";
  const zone = document.getElementById("upload");
  if (!zone) return;
  const token = document.querySelector('meta[name="batchslicer-token"]').content;
  const status = zone.querySelector(".upload-status");
  const maxBytes = Number(zone.dataset.maxMb) * 1024 * 1024;
  let busy = false;

  const say = (text, isError = false) => {
    status.textContent = text;
    status.classList.toggle("error", isError);
  };

  // Every file below a dropped entry, with its path from the entry's parent.
  const filesIn = (entry, prefix) => new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => resolve([[prefix + file.name, file]]), () => resolve([]));
      return;
    }
    const reader = entry.createReader();
    const found = [];
    const readMore = () => reader.readEntries(async (entries) => {
      if (entries.length === 0) {
        resolve(found);
        return;
      }
      for (const child of entries) found.push(...await filesIn(child, prefix + entry.name + "/"));
      readMore();
    }, () => resolve(found));
    readMore();
  });

  const send = (pairs) => {
    if (busy || pairs.length === 0) return;
    const total = pairs.reduce((sum, [, file]) => sum + file.size, 0);
    if (total > maxBytes) {
      say(`Too large: at most ${zone.dataset.max} at a time.`, true);
      return;
    }
    const form = new FormData();
    const target = zone.querySelector('select[name="target"]');
    if (target) form.append("target", target.value);
    for (const [path, file] of pairs) {
      form.append("path", path);
      form.append("file", file, file.name);
    }
    const request = new XMLHttpRequest();
    request.open("POST", "/upload");
    request.setRequestHeader("X-BatchSlicer-Token", token);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) say(`Uploading… ${Math.round((100 * event.loaded) / event.total)}%`);
    };
    request.onload = () => {
      busy = false;
      let answer = {};
      try { answer = JSON.parse(request.responseText); } catch { /* not JSON */ }
      if (request.status !== 200) {
        say(answer.error || `The upload failed (${request.status}).`, true);
        return;
      }
      const added = answer.added.length ? `Added ${answer.added.join(", ")}.` : "Nothing to slice was uploaded.";
      const skipped = answer.skipped.length ? ` Skipped ${answer.skipped.length} other file(s).` : "";
      say(added + skipped, answer.added.length === 0);
      const queue = document.getElementById("queue");
      if (queue && window.htmx) window.htmx.trigger(queue, "refresh");
    };
    request.onerror = () => {
      busy = false;
      say("The upload failed: is BatchSlicer still running?", true);
    };
    busy = true;
    say("Uploading…");
    request.send(form);
  };

  for (const input of zone.querySelectorAll('input[type="file"]')) {
    input.addEventListener("change", () => {
      send([...input.files].map((file) => [file.webkitRelativePath || file.name, file]));
      input.value = "";
    });
  }
  for (const name of ["dragenter", "dragover"]) {
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("over");
    });
  }
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", async (event) => {
    event.preventDefault();
    zone.classList.remove("over");
    const entries = [...event.dataTransfer.items]
      .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
      .filter(Boolean);
    if (entries.length) {
      const pairs = [];
      for (const entry of entries) pairs.push(...await filesIn(entry, ""));
      send(pairs);
    } else {
      send([...event.dataTransfer.files].map((file) => [file.name, file]));
    }
  });
})();

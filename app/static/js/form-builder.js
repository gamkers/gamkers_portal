(() => {
  const form = document.getElementById("form-editor");
  if (!form) return;

  const list = document.getElementById("question-list");
  const questionsInput = document.getElementById("questions-data");
  let questions = JSON.parse(form.dataset.questions || "[]");

  const newQuestion = (type = "short_text", title = "") => ({
    id: `q_${crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "").slice(0, 12) : Date.now().toString(36)}`,
    title,
    type,
    required: false,
    options: type === "choice" || type === "checkbox" ? ["Option 1", "Option 2"] : [],
  });

  if (!questions.length) {
    questions = [
      { ...newQuestion("short_text", "Your name"), required: true },
      { ...newQuestion("email", "Your email"), required: true },
    ];
  }

  function element(tag, attributes = {}, text = "") {
    const node = document.createElement(tag);
    Object.entries(attributes).forEach(([key, value]) => {
      if (key === "className") node.className = value;
      else node.setAttribute(key, value);
    });
    if (text) node.textContent = text;
    return node;
  }

  function render() {
    list.replaceChildren();
    questions.forEach((question, index) => {
      const card = element("article", { className: "question-card" });
      const top = element("div", { className: "question-card-top" });
      top.append(element("span", { className: "question-number" }, `QUESTION ${String(index + 1).padStart(2, "0")}`));
      const remove = element("button", { className: "button button-quiet button-small", type: "button" }, "Remove");
      remove.addEventListener("click", () => {
        questions = questions.filter((item) => item.id !== question.id);
        render();
      });
      top.append(remove);
      card.append(top);

      const titleLabel = element("label", { className: "field-label" }, "Question");
      const title = element("input", { className: "question-title", maxlength: "240", required: "" });
      title.value = question.title;
      title.addEventListener("input", () => { question.title = title.value; });
      titleLabel.append(title);
      card.append(titleLabel);
      card.append(element("p", { className: "question-placeholder" }, `Email placeholder: {${question.id}}`));

      const controls = element("div", { className: "question-controls" });
      const typeLabel = element("label", { className: "field-label" }, "Answer type");
      const type = element("select", { className: "question-type" });
      [
        ["short_text", "Short answer"],
        ["long_text", "Long answer"],
        ["email", "Email address"],
        ["number", "Number"],
        ["date", "Date"],
        ["choice", "Multiple choice"],
        ["checkbox", "Checkboxes"],
      ].forEach(([value, label]) => {
        const option = element("option", { value }, label);
        option.selected = question.type === value;
        type.append(option);
      });
      type.addEventListener("change", () => {
        question.type = type.value;
        question.options = ["choice", "checkbox"].includes(type.value) ? ["Option 1", "Option 2"] : [];
        render();
      });
      typeLabel.append(type);
      controls.append(typeLabel);

      const requiredLabel = element("label", { className: "check-label required-toggle" }, "Required");
      const required = element("input", { type: "checkbox" });
      required.checked = question.required;
      required.addEventListener("change", () => { question.required = required.checked; });
      requiredLabel.prepend(required);
      controls.append(requiredLabel);
      card.append(controls);

      if (["choice", "checkbox"].includes(question.type)) {
        const optionsLabel = element("label", { className: "field-label" }, "Options (one per line)");
        const options = element("textarea", { className: "question-options", rows: "3" });
        options.value = question.options.join("\n");
        options.addEventListener("input", () => {
          question.options = options.value.split("\n").map((item) => item.trim()).filter(Boolean);
        });
        optionsLabel.append(options);
        card.append(optionsLabel);
      }
      list.append(card);
    });
  }

  document.getElementById("add-question").addEventListener("click", () => {
    questions.push(newQuestion());
    render();
    list.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  form.addEventListener("submit", () => {
    questionsInput.value = JSON.stringify(questions);
  });

  render();
})();

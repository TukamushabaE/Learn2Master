document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('input[type="password"]').forEach((input, index) => {
        if (input.closest(".password-field")) return;

        const wrapper = document.createElement("span");
        wrapper.className = "password-field";
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        if (!input.id) input.id = `password-field-${index + 1}`;

        const button = document.createElement("button");
        button.type = "button";
        button.className = "password-toggle";
        button.textContent = "Show";
        button.setAttribute("aria-controls", input.id);
        button.setAttribute("aria-label", "Show password");
        button.setAttribute("aria-pressed", "false");

        button.addEventListener("click", () => {
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            button.textContent = showing ? "Show" : "Hide";
            button.setAttribute("aria-label", showing ? "Show password" : "Hide password");
            button.setAttribute("aria-pressed", String(!showing));
        });

        wrapper.appendChild(button);
    });
});

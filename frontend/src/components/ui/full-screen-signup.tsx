"use client";

import { FormEvent, useState } from "react";

type FullScreenSignupProps = {
  initialUsername?: string;
  error?: string;
  loading?: boolean;
  onSubmit: (username: string, password: string) => Promise<void> | void;
};

const companyLogoSrc = `${import.meta.env.BASE_URL}brand/demo-logo.svg`;

export const FullScreenSignup = ({
  initialUsername = "admin",
  error = "",
  loading = false,
  onSubmit
}: FullScreenSignupProps) => {
  const [username, setUsername] = useState(initialUsername);
  const [password, setPassword] = useState("");
  const [usernameError, setUsernameError] = useState("");
  const [passwordError, setPasswordError] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    let valid = true;

    if (!username.trim()) {
      setUsernameError("请输入账号。");
      valid = false;
    } else {
      setUsernameError("");
    }

    if (!password) {
      setPasswordError("请输入密码。");
      valid = false;
    } else {
      setPasswordError("");
    }

    if (!valid) return;
    await onSubmit(username.trim(), password);
  };

  return (
    <div className="flex min-h-screen items-center justify-center overflow-hidden bg-[#ece9e2] px-4 py-8 text-[#171717]">
      <div className="relative flex w-full max-w-5xl flex-col overflow-hidden rounded-[28px] bg-[#f7f4ee] shadow-[0_28px_90px_rgba(20,20,20,0.22)] md:min-h-[640px] md:flex-row">
        <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-t from-transparent via-transparent to-black/45" />
        <div className="pointer-events-none absolute left-0 top-0 z-20 hidden h-full overflow-hidden backdrop-blur-2xl md:flex">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="h-[44rem] w-16 bg-gradient-to-r from-transparent via-black/70 via-[69%] to-white/20 opacity-25"
            />
          ))}
        </div>
        <div className="pointer-events-none absolute -bottom-20 -left-16 z-0 h-64 w-64 rounded-full bg-[#f97316]" />
        <div className="pointer-events-none absolute -bottom-12 left-8 z-0 h-24 w-36 rounded-full bg-white" />
        <div className="pointer-events-none absolute -bottom-10 left-28 z-0 h-20 w-32 rounded-full bg-white/80" />

        <section className="relative z-30 flex min-h-[280px] flex-col justify-between overflow-hidden bg-black px-8 py-9 text-white md:w-1/2 md:p-12">
          <div className="flex items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-white p-2 shadow-[0_16px_34px_rgba(249,115,22,0.24)]">
              <img src={companyLogoSrc} alt="星河演示商贸有限公司" className="h-full w-full object-contain" />
            </div>
            <div>
              <p className="m-0 text-sm font-semibold text-white/70">星河演示商贸有限公司</p>
              <p className="m-0 text-base font-semibold">管理中心</p>
            </div>
          </div>
          <div className="max-w-sm">
            <p className="mb-4 text-sm font-semibold tracking-[0.18em] text-[#f97316]">星河演示商贸有限公司</p>
            <h1 className="m-0 text-3xl font-medium leading-tight tracking-tight md:text-4xl">
              企业管理中心
            </h1>
          </div>
        </section>

        <section className="relative z-30 flex flex-1 flex-col justify-center bg-[#f7f4ee] px-8 py-9 text-[#171717] md:w-1/2 md:p-12">
          <div className="mb-8">
            <div className="mb-4 grid h-14 w-14 place-items-center rounded-xl bg-white p-2 shadow-sm">
              <img src={companyLogoSrc} alt="星河演示商贸有限公司" className="h-full w-full object-contain" />
            </div>
            <h2 className="mb-2 text-3xl font-medium tracking-tight text-[#171717]">登录管理中心</h2>
            <p className="m-0 text-sm font-medium text-[#66615a]">使用管理员分配的账号登录</p>
          </div>

          {error ? (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-600">
              {error}
            </div>
          ) : null}

          <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
            <div>
              <label htmlFor="username" className="mb-2 block text-sm font-medium text-[#332f2a]">
                账号
              </label>
              <input
                id="username"
                className={`w-full rounded-lg border bg-white px-3 py-3 text-sm font-medium text-black outline-none transition focus:ring-1 focus:ring-[#f97316] ${
                  usernameError ? "border-red-500" : "border-[#d8d3ca]"
                }`}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                aria-invalid={!!usernameError}
                aria-describedby="username-error"
              />
              {usernameError ? (
                <p id="username-error" className="mt-1 text-xs font-semibold text-red-500">
                  {usernameError}
                </p>
              ) : null}
            </div>

            <div>
              <label htmlFor="password" className="mb-2 block text-sm font-medium text-[#332f2a]">
                密码
              </label>
              <input
                id="password"
                type="password"
                className={`w-full rounded-lg border bg-white px-3 py-3 text-sm font-medium text-black outline-none transition focus:ring-1 focus:ring-[#f97316] ${
                  passwordError ? "border-red-500" : "border-[#d8d3ca]"
                }`}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                aria-invalid={!!passwordError}
                aria-describedby="password-error"
              />
              {passwordError ? (
                <p id="password-error" className="mt-1 text-xs font-semibold text-red-500">
                  {passwordError}
                </p>
              ) : null}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-2 w-full rounded-lg bg-[#f97316] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#ea580c] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "正在登录" : "进入系统"}
            </button>
          </form>

          <div className="mt-5 text-center text-sm font-medium text-[#6c665e]">
            忘记密码请联系管理员
          </div>
        </section>
      </div>
    </div>
  );
};

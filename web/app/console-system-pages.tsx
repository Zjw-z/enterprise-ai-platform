/* eslint-disable react-hooks/set-state-in-effect -- effects load remote control-plane state */
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api } from "./api-client";
import type { CurrentUser, MenuNode } from "./console-types";
import {
  DataTable,
  EmptyState,
  Modal,
  ObjectCards,
  PageHeading,
  Status,
  allows,
  formatDate,
  normalizeRecords,
} from "./console-support";

export function UsersPage({ user, notify }: { user: CurrentUser; notify: (value: string) => void }) {
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [roles, setRoles] = useState<Record<string, unknown>[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const load = useCallback(async () => {
    const [users, roleItems] = await Promise.all([
      api.request<Record<string, unknown>[]>("/v1/system/users"),
      api.request<Record<string, unknown>[]>("/v1/system/roles"),
    ]);
    setItems(users);
    setRoles(roleItems);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api.request("/v1/system/users", {
      method: "POST",
      body: JSON.stringify({
        username: form.get("username"),
        display_name: form.get("display_name"),
        password: form.get("password"),
        role_ids: form.get("role_id") ? [form.get("role_id")] : [],
      }),
    });
    setShowCreate(false);
    notify("用户创建成功");
    await load();
  };
  return (
    <>
      <PageHeading eyebrow="SYSTEM / IAM" title="用户管理" description="管理平台登录用户与角色归属。" action={allows(user, "system:user:create") ? <button className="primary-button" onClick={() => setShowCreate(true)}>新建用户</button> : undefined} />
      <section className="panel">
        <DataTable
          columns={["用户名", "姓名", "角色", "状态", "最近登录"]}
          rows={items.map((item) => [
            String(item.username),
            String(item.display_name),
            Array.isArray(item.roles) ? item.roles.join(", ") : "—",
            <Status key="status" value={String(item.status)} />,
            item.last_login_at ? formatDate(String(item.last_login_at)) : "尚未登录",
          ])}
        />
      </section>
      {showCreate && (
        <Modal title="新建用户" onClose={() => setShowCreate(false)}>
          <form className="stack-form" onSubmit={create}>
            <label>用户名<input name="username" required minLength={2} /></label>
            <label>显示名称<input name="display_name" required /></label>
            <label>初始密码<input name="password" type="password" required minLength={8} /></label>
            <label>角色<select name="role_id"><option value="">暂不分配</option>{roles.map((role) => <option key={String(role.id)} value={String(role.id)}>{String(role.name)}</option>)}</select></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">保存用户</button></div>
          </form>
        </Modal>
      )}
    </>
  );
}

export function RolesPage({ user, notify }: { user: CurrentUser; notify: (value: string) => void }) {
  const [roles, setRoles] = useState<Record<string, unknown>[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const load = useCallback(async () => setRoles(await api.request("/v1/system/roles")), []);
  useEffect(() => { void load(); }, [load]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api.request("/v1/system/roles", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        code: form.get("code"),
        description: form.get("description"),
        permissions: String(form.get("permissions") || "").split("\n").map((item) => item.trim()).filter(Boolean),
      }),
    });
    setShowCreate(false);
    notify("角色创建成功");
    await load();
  };
  return (
    <>
      <PageHeading eyebrow="SYSTEM / RBAC" title="角色管理" description="角色同时承载菜单授权和后端权限标识。" action={allows(user, "system:role:create") ? <button className="primary-button" onClick={() => setShowCreate(true)}>新建角色</button> : undefined} />
      <section className="panel">
        <DataTable
          columns={["角色名称", "角色编码", "权限数量", "状态", "类型"]}
          rows={roles.map((role) => [
            String(role.name),
            <code key="code">{String(role.code)}</code>,
            Array.isArray(role.permissions) ? role.permissions.length : 0,
            <Status key="status" value={String(role.status)} />,
            role.builtin ? "系统内置" : "自定义",
          ])}
        />
      </section>
      {showCreate && (
        <Modal title="新建角色" onClose={() => setShowCreate(false)}>
          <form className="stack-form" onSubmit={create}>
            <label>角色名称<input name="name" required /></label>
            <label>角色编码<input name="code" required /></label>
            <label>描述<input name="description" /></label>
            <label>权限标识（每行一个）<textarea name="permissions" rows={6} placeholder="business:weather:use" /></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">保存角色</button></div>
          </form>
        </Modal>
      )}
    </>
  );
}

export function MenusPage({ menus: myMenus }: { menus: MenuNode[] }) {
  const [menus, setMenus] = useState<MenuNode[]>([]);
  useEffect(() => {
    void api.request<MenuNode[]>("/v1/system/menus/tree").then(setMenus);
  }, [myMenus]);
  return (
    <>
      <PageHeading eyebrow="SYSTEM / ROUTING" title="菜单管理" description="目录、页面和按钮权限共同生成用户动态路由。" />
      <section className="panel menu-tree-panel">
        <div className="menu-tree-header"><span>菜单名称</span><span>路由</span><span>权限标识</span><span>模块</span><span>状态</span></div>
        {menus.map((menu) => <MenuTreeRow key={menu.id} menu={menu} depth={0} />)}
      </section>
    </>
  );
}

function MenuTreeRow({ menu, depth }: { menu: MenuNode & Record<string, unknown>; depth: number }) {
  return (
    <>
      <div className="menu-tree-row">
        <span style={{ paddingLeft: `${depth * 24}px` }}><b>{menu.children?.length ? "▾" : "·"}</b>{menu.name}</span>
        <code>{menu.path || "—"}</code>
        <code>{menu.permission || "—"}</code>
        <span>{String(menu.module || "system")}</span>
        <Status value={menu.enabled === false ? "disabled" : "enabled"} />
      </div>
      {menu.children?.map((child) => <MenuTreeRow key={child.id} menu={child} depth={depth + 1} />)}
    </>
  );
}

export function ResourcePage({ title, description, endpoint }: { title: string; description: string; endpoint: string }) {
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void api.request(endpoint).then(setData).catch((reason) => setError(reason.message));
  }, [endpoint]);
  const records = normalizeRecords(data);
  return (
    <>
      <PageHeading eyebrow="AI ASSET MANAGEMENT" title={title} description={description} action={<button className="secondary-button" onClick={() => window.location.reload()}>刷新</button>} />
      {error ? <EmptyState title="数据加载失败" description={error} /> : (
        <section className="panel">
          {records.length ? <ObjectCards records={records} /> : <EmptyState title="暂无数据" description="启动配置中尚未注册对应资源。" />}
        </section>
      )}
    </>
  );
}

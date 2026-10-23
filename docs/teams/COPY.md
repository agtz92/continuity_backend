# Crew — texto de interfaz, ES y EN

> **Estado:** inglés escrito por el agente de marca (2026-09-16). El español lleva las
> correcciones que salieron de esa pasada. Las claves son el contrato con el código y **no se
> renombran**.
>
> Reglas de implementación en [`PLAN.md` §10](PLAN.md). Producto y planes en [`PLANES.md`](PLANES.md).

---

## 0. Qué quedó pendiente de decidir

Uno, y es de formato, no de idioma: **«Log» contra «Bitácora».** La navegación del Crew dice
«Log» en español, pero el producto en español lo llama «Bitácora» (`tabs.log`). Hay que decidir
si el Crew se alinea o si «Bitácora» se retira también del espacio personal. En inglés es *Log*
en los dos casos.

### Lo que se resolvió en esta pasada

| Hallazgo | Resolución |
|---|---|
| Seis plurales rotos en el español | **Corregidos abajo.** Eran míos |
| «tu jefe» en `crew.personal.quotaNote` | Cambiado a «nadie del Crew». Contradecía §1.7 del plan |
| «El Crew lo paga quien te invita» | Cambiado a «el dueño del Crew». Un lead que no es dueño puede invitar |
| `crew.switcher.codeHint` | **Eliminado.** Es una anotación del canvas, no copy |
| «Studio» y «20:00» fijos | Pasan a `{plan}` y a hora formateada por locale |
| Micro contra Free | Es **Micro**. El rename se cerró el 15 de septiembre |
| El ritual del Crew contra el *Sunday Review* de la marca | **No es problema.** El del Crew se llama Revisión / **Review**, y ya. El *Sunday Review* sigue siendo material de marca del producto personal |
| «Equipo» contra «Crew» | **Crew en los dos idiomas.** Una sola palabra para el espacio y para la gente |
| La firma del correo | **Fuera.** El correo habla en nombre de quien invita |

---

## 1. Glosario

### Lo que ya existía y no se re-decidió

| ES | EN |
|---|---|
| Cementerio · Atorados · Muerto · Pausado · Vivió · Murió de | **Graveyard · Stuck · Killed · Paused · Lived · Died of** |
| Captura rápida · Alta/Media/Baja | **Quick capture · High/Medium/Low** |
| Hoy · Proyectos · Tareas · Rutinas · Ideas · Notas · Calendario · Analíticas | **Today · Projects · Tasks · Routines · Ideas · Notes · Calendar · Analytics** |

### Las ocho decisiones nuevas

| ES | EN | Por qué |
|---|---|---|
| Pulso | **Pulse** | No choca con nada del producto y cabe en la barra de móvil |
| Crew | **Crew** | Sin cambio |
| Revisión | **Review** | Mayúscula: es un objeto del producto |
| Se está enfriando | **Drifting** | Es léxico de marca: *"The drift is what kills builders."* El tramo de 8 a 21 días es exactamente el drift |
| Reparto | **Who's carrying what** | «Workload» suena a panel de recursos humanos. «Carrying» habla de peso, no de rendimiento |
| Te proponen | **Proposed to you** | Par verbo/sustantivo: *propose / proposal*. Rechazar es **Pass**, no *Reject* |
| Lo mío del Crew | **My Crew work** | Primera persona conservada |
| lead / member | **lead / member** en frase, **Lead / Member** como etiqueta | Minúscula dentro de frase para que no suene a cargo |

Dos más que el agente añadió y conviene fijar: **Kill it** para el verbo (*"Killing is a form of
finishing"*) y **Make the call** como llamada a la acción de la Revisión.

---

## 2. Chrome compartido

### 2.1 `crew.nav.*`

| Clave | ES | EN |
|---|---|---|
| `crew.nav.groupTeam` | Crew | Crew |
| `crew.nav.groupWork` | Trabajo | Work |
| `crew.nav.groupRecord` | Registro | Record |
| `crew.nav.pulse` | Pulso | Pulse |
| `crew.nav.members` | Miembros | Members |
| `crew.nav.projects` | Proyectos | Projects |
| `crew.nav.tasks` | Tareas | Tasks |
| `crew.nav.calendar` | Calendario | Calendar |
| `crew.nav.graveyard` | Cementerio | Graveyard |
| `crew.nav.log` | Log | Log |
| `crew.nav.stuck` | Atorado | Stuck |
| `crew.nav.emptyCounters` | Sin contadores: todavía no hay nada | No counts yet. Nothing to count. |

### 2.2 `crew.switcher.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.switcher.personal` | Personal | Personal | |
| `crew.switcher.personalHint` | {plan} · siempre el primero | {plan} · always first | `{plan}` era «Studio» fijo |
| `crew.switcher.roleLead` | Crew · lead | Crew · lead | |
| `crew.switcher.roleMember` | Crew · miembro | Crew · member | |
| `crew.switcher.planLine` | Crew · {plan} | Crew · {plan} | |
| `crew.switcher.create` | Crear Crew | New Crew | |

### 2.3 `crew.actions.*`

| Clave | ES | EN |
|---|---|---|
| `crew.actions.assign` | + Asignar tarea | + Assign task |
| `crew.actions.propose` | + Proponer tarea | + Propose task |

---

## 3. Pulso

### 3.1 `crew.pulse.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.pulse.title` | Pulso | Pulse | |
| `crew.pulse.cooling` | Se está enfriando | Drifting | |
| `crew.pulse.coolingCount` | `{count} de {total, plural, one {# proyecto} other {# proyectos}}` | `{count} of {total, plural, one {# project} other {# projects}}` | **Corregido:** el plural concuerda con `{total}`, no con `{count}` |
| `crew.pulse.daysUntouched` | `{days, plural, other {# d sin tocar}}` | `{days, plural, other {#d untouched}}` | ▸ ancho |
| `crew.pulse.blockedDays` | `{days, plural, other {bloqueada # d}}` | `{days, plural, other {blocked #d}}` | |
| `crew.pulse.nextStep` | siguiente paso: {step} | next step: {step} | |
| `crew.pulse.noNextStep` | sin siguiente paso | no next step | |
| `crew.pulse.workload` | Reparto | Who's carrying what | |
| `crew.pulse.workloadHint` | para que nadie cargue de más | so nobody carries too much | **Corregido:** nombra el cuidado, no la medición (§1.7) |
| `crew.pulse.openTasks` | `{count, plural, one {# abierta} other {# abiertas}}` | `{count, plural, other {# open}}` | ▸ ancho |
| `crew.pulse.projectCount` | `{count, plural, one {# proyecto} other {# proyectos}}` | `{count, plural, one {# project} other {# projects}}` | ▸ ancho |
| `crew.pulse.closedThisWeek` | `{count, plural, one {# cerrada esta semana} other {# cerradas esta semana}}` | `{count, plural, other {# closed this week}}` | |
| `crew.pulse.proposalsInbox` | Te proponen | Proposed to you | |
| `crew.pulse.proposalsPending` | `{count, plural, one {# pendiente} other {# pendientes}}` | `{count, plural, other {# waiting}}` | |
| `crew.pulse.proposedBy` | De {name} · vence {due} · {effort} | From {name} · due {due} · {effort} | El encabezado ya dice que te la proponen |
| `crew.pulse.accept` | Aceptar | Accept | |
| `crew.pulse.decline` | Rechazar | Pass | |

### 3.2 `crew.pulse.member.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.pulse.member.coolingMine` | Se está enfriando · lo tuyo | Drifting · yours | |
| `crew.pulse.member.coolingHint` | antes de que el lead tenga que preguntar | before the lead has to ask | «tenga que» hace la promesa explícita |
| `crew.pulse.member.mine` | Lo mío del Crew | My Crew work | |
| `crew.pulse.member.assignedByLead` | te la asignó el lead | assigned by the lead | |
| `crew.pulse.member.mineTag` | tuya | yours | |
| `crew.pulse.member.sentToLead` | Para el lead · enviada {when} | To the lead · sent {when} | |
| `crew.pulse.member.acceptedOn` | Para el lead · aceptada {when} | To the lead · accepted {when} | |
| `crew.pulse.member.statusPending` | pendiente | pending | `.meta`, el CSS pone la versalita |
| `crew.pulse.member.statusAccepted` | aceptada | accepted | `.meta` |
| `crew.pulse.member.sharedProjects` | Proyectos del Crew donde participo | Crew projects I'm in | |

### 3.3 `crew.pulse.empty.*`

| Clave | ES | EN |
|---|---|---|
| `crew.pulse.empty.title` | Aquí no hay nadie más | It's just you in here. |
| `crew.pulse.empty.body` | Un Crew de una persona es tu espacio personal con pasos de más. En cuanto entre alguien, esta pantalla te dice qué empezaron y nadie ha tocado. | A Crew of 1 is your personal space with extra steps. The moment someone joins, this screen shows what got started and what nobody's touched since. |
| `crew.pulse.empty.preview` | Aquí irá | What you'll see here |

---

## 4. Tareas y asignación

### 4.1 `crew.tasks.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.tasks.summary` | `{open, plural, one {# abierta} other {# abiertas}} · {stuck, plural, one {# atorada} other {# atoradas}}` | {open} open · {stuck} stuck | **Corregido:** el español necesita ICU, el inglés no |
| `crew.tasks.filterAll` | Todas | All | ▸ ancho |
| `crew.tasks.filterUnassigned` | Sin asignar | Unassigned | ▸ ancho |
| `crew.tasks.filterYou` | Tú | Me | Dos letras en los dos idiomas: en el avatar no caben tres |
| `crew.tasks.groupOverdue` | `{count, plural, one {Vencida · #} other {Vencidas · #}}` | `{count, plural, other {Overdue · #}}` | |
| `crew.tasks.overdueDays` | `{days, plural, other {vencida · # d}}` | `{days, plural, other {overdue · #d}}` | |
| `crew.tasks.noProject` | Sin proyecto | No project | |
| `crew.tasks.noTime` | Sin hora | No time set | *No time* solo se leería como «no tengo tiempo» |

### 4.2 `crew.assign.*`

| Clave | ES | EN |
|---|---|---|
| `crew.assign.titleLead` | Asignar tarea | Assign a task |
| `crew.assign.titleMember` | Proponer tarea | Propose a task |
| `crew.assign.badgeDirect` | directo | direct |
| `crew.assign.badgeProposal` | propuesta | proposal |
| `crew.assign.badgeYouAreLead` | directo · eres lead | direct · you're a lead |
| `crew.assign.fieldAssignTo` | Asignar a | Assign to |
| `crew.assign.fieldProposeTo` | Proponer a | Propose to |
| `crew.assign.fieldProject` | Proyecto | Project |
| `crew.assign.fieldDue` | Vence | Due |
| `crew.assign.fieldEffort` | Esfuerzo | Effort |
| `crew.assign.fieldPriority` | Prioridad | Priority |
| `crew.assign.fieldNote` | Nota | Note |
| `crew.assign.roleMember` | Miembro | Member |
| `crew.assign.roleLead` | Lead | Lead |
| `crew.assign.optionLead` | El lead | The lead |
| `crew.assign.submitAssign` | Asignar | Assign |
| `crew.assign.submitPropose` | Proponer | Propose |
| `crew.assign.footerAssign` | Aparece ya en su lista. Le llega una notificación. | It's on their list now. They'll get a notification. |
| `crew.assign.footerPropose` | No aparece en su lista hasta que la acepte. | It stays off their list until they accept it. |

---

## 5. La Revisión

### 5.1 `crew.review.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.review.eyebrow` | {crew} · Revisión | {crew} · Review | |
| `crew.review.weekOf` | Semana del {from} al {to} | Week of {from} to {to} | |
| `crew.review.progress` | {current} de {total} | {current} of {total} | |
| `crew.review.question` | ¿Qué pasa con esto? | What's the call on this one? | El inglés conecta con *Make the call* |
| `crew.review.lastActivity` | Lo último | Last activity | |
| `crew.review.nextStepLabel` | Siguiente paso | Next step | |
| `crew.review.stuckLabel` | Atorado | Stuck | |
| `crew.review.optContinue` | Sigue | Keep going | |
| `crew.review.optContinueHint` | Pide un siguiente paso nuevo | Needs a new next step | |
| `crew.review.optPause` | Se pausa | Pause it | |
| `crew.review.optPauseHint` | Contexto, siguiente acción y qué lo bloquea | Context, next action, and what's blocking it | |
| `crew.review.optKill` | Se mata | Kill it | |
| `crew.review.optKillHint` | Razón, qué aprendiste, si lo reharías | Why, what you learned, and whether you'd do it again | |
| `crew.review.nextStepPrompt` | Entonces, ¿cuál es el siguiente paso? | So what's the next step? | |
| `crew.review.continueWarning` | Seguir no es gratis. Si no hay siguiente paso, el proyecto no sigue: está pausado y todavía no lo dices. | Keeping it isn't free. Without a next step, it isn't moving. It's paused. You just haven't said it yet. | La frase citable de la pantalla |
| `crew.review.saveNext` | Guardar y siguiente | Save and next | |
| `crew.review.remaining` | `{count, plural, =0 {Este es el último} one {queda # después de este} other {quedan # después de este}}` | `{count, plural, =0 {This is the last one} other {# more after this one}}` | **Corregido:** faltaba el caso 0 |
| `crew.review.alreadyDecided` | Ya decidiste | Already decided | |
| `crew.review.autoClose` | Se cierra sola el domingo a las {time}. No hace falta que nadie la cierre. | Closes on its own Sunday at {time}. Nobody has to close it. | |
| `crew.review.stateContinues` | sigue | keep going | `.meta` |
| `crew.review.statePaused` | se pausa | pause | `.meta` |
| `crew.review.stateKilled` | se mata | kill | `.meta` |

### 5.2 `crew.review.lead.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.review.lead.title` | Ya está contestada | The calls are already made. | Lo que compra Table |
| `crew.review.lead.answeredBy` | {names} | {names} | |
| `crew.review.lead.groupContinues` | `{count, plural, other {Sigue · #}}` | `{count, plural, other {Keeps going · #}}` | |
| `crew.review.lead.groupContinuesHint` | cada uno con su siguiente paso | each with its next step | |
| `crew.review.lead.groupPaused` | `{count, plural, one {Se pausó · #} other {Se pausaron · #}}` | `{count, plural, other {Paused · #}}` | |
| `crew.review.lead.groupKilled` | `{count, plural, one {Se mató · #} other {Se mataron · #}}` | `{count, plural, other {Killed · #}}` | |
| `crew.review.lead.killedHint` | ya está en el Cementerio del Crew | already in the Crew's Graveyard | |
| `crew.review.lead.closeNote` | Se cierra sola el domingo a las {time}. El botón existe porque a veces ya terminaron. | Closes on its own Sunday at {time}. The button's here because sometimes you're done early. | |
| `crew.review.lead.close` | Cerrar la Revisión | Close the Review | |

---

## 6. Cementerio compartido

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.graveyard.title` | Cementerio | Graveyard | |
| `crew.graveyard.subtitle` | Lo que este Crew decidió no terminar, y por qué. | What this Crew decided not to finish, and why. | |
| `crew.graveyard.totalProjects` | `{count, plural, one {# proyecto} other {# proyectos}}` | `{count, plural, one {# project} other {# projects}}` | |
| `crew.graveyard.totalDays` | `{days, plural, one {# día de vida sumado} other {# días de vida sumados}}` | `{days, plural, one {# day of life, combined} other {# days of life, combined}}` | |
| `crew.graveyard.groupThisMonth` | Este mes · {count} | This month · {count} | |
| `crew.graveyard.groupEarlier` | Antes | Earlier | |
| `crew.graveyard.learned` | Aprendimos: {learning} | We learned: {learning} | |
| `crew.graveyard.lived` | `Vivió {days, plural, one {# día} other {# días}} · murió con {open, plural, one {# tarea abierta} other {# tareas abiertas}}` | `Lived {days, plural, one {# day} other {# days}} · died with {open, plural, one {# open task} other {# open tasks}}` | Eco de *Lived · Died of* |
| `crew.graveyard.livedShort` | `{days} d · {open, plural, one {# abierta} other {# abiertas}}` | `{days}d · {open} open` | **Corregido** en español |
| `crew.graveyard.revive` | Revivir | Revive | |
| `crew.graveyard.empty` | Todavía no han matado nada. | Nothing's been killed yet. | |
| `crew.graveyard.noAutopsy` | Aquí solo está el registro. La lectura del patrón sigue en tu Cementerio personal, con Loop. | This is only the record. Reading the pattern still happens in your personal Graveyard, with Loop. | Loop es nombre propio, sin posesivo |

---

## 7. Entrar a un Crew

### 7.1 `crew.onboarding.*`

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.onboarding.eyebrow` | {crew} · recién creado | {crew} · just created | |
| `crew.onboarding.notAWizard` | Esto no es un asistente de pasos. Es lo que le falta al Crew, derivado del Crew mismo. | This isn't a setup wizard. It's what the Crew is still missing, read from the Crew itself. | |
| `crew.onboarding.missing` | Le falta | Still missing | |
| `crew.onboarding.progress` | {done} de {total} listo | {done} of {total} done | |
| `crew.onboarding.stepName` | Ponle nombre | Name it | |
| `crew.onboarding.stepNameDone` | {name} · de ahí sale el código «{code}» del switch | {name} · that's where the {code} in the switcher comes from | |
| `crew.onboarding.stepInvite` | Invita a alguien | Invite someone | |
| `crew.onboarding.stepInviteSent` | Mandaste una a {email}. En cuanto acepte, este paso se cierra solo. | You sent one to {email}. Once they accept, this step checks itself off. | |
| `crew.onboarding.inviteExpiry` | `Caduca en {days, plural, one {# día} other {# días}} · mientras tanto aparta un asiento` | `Expires in {days, plural, one {# day} other {# days}} · holds a seat until then` | |
| `crew.onboarding.resend` | Reenviar | Resend | |
| `crew.onboarding.stepWork` | Trae trabajo de verdad | Bring in real work | |
| `crew.onboarding.stepWorkBody` | Mueve un proyecto tuyo aquí. Es más útil que empezar uno nuevo: ver algo tuyo volverse visible para otra persona es de lo que va esto. | Move one of your projects here. It beats starting a new one. Watching your own work become visible to someone else is the whole point. | |
| `crew.onboarding.projectsAllowed` | `En {plan} caben {count, plural, one {# proyecto compartido} other {# proyectos compartidos}}` | `{plan} fits {count, plural, one {# shared project} other {# shared projects}}` | **Corregido** en español |
| `crew.onboarding.chooseProject` | Elegir proyecto | Pick a project | |
| `crew.onboarding.stepReview` | ¿Cuándo es la Revisión? | When's the Review? | |
| `crew.onboarding.stepReviewBody` | Si no se agenda, el ritual no existe. Elige día y hora y te decimos la fecha de la primera. | If it's not on the calendar, the ritual doesn't exist. Pick a day and time and we'll tell you when the first one lands. | |
| `crew.onboarding.reviewSuggested` | Sugerido: {day}, {time} | Suggested: {day}, {time} | **Corregido:** la hora la formatea el locale |
| `crew.onboarding.schedule` | Agendar | Schedule it | |
| `crew.onboarding.notSaved` | Nada de esto se guarda como «paso completado»: se deriva del Crew. Si el único miembro se va, la lista vuelve sola. | None of this is saved as a "completed step." It's read from the Crew. If your only member leaves, the list comes back on its own. | |
| `crew.onboarding.dismiss` | Ocultar | Hide | |
| `crew.onboarding.meanwhile` | Mientras tanto | In the meantime | |

### 7.2 `crew.invite.*`

**La más importante del conjunto.** Se lee sin sesión iniciada, casi siempre en el teléfono.

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.invite.from` | {name} te invita a | {name} invited you to | |
| `crew.invite.whatIsIt` | Es un Crew: un espacio compartido, aparte de tu cuenta. | It's a Crew: a shared space, separate from your account. | |
| `crew.invite.seeLabel` | Qué van a ver | What they'll see | ▸ ancho |
| `crew.invite.seeBody` | Los proyectos y tareas que tengas **en este Crew**. Nada más. | The projects and tasks you keep **in this Crew**. Nothing else. | |
| `crew.invite.privateLabel` | Qué no ve nadie | What nobody sees | |
| `crew.invite.privateBody` | **Tu espacio personal.** Tus proyectos, ideas, rutinas y notas siguen siendo solo tuyos, y no aparecen aquí ni aunque el dueño pague el plan más caro. | **Your personal space.** Your projects, ideas, routines, and notes stay yours. They don't show up here, not even if the owner pays for the biggest plan. | |
| `crew.invite.canLabel` | Qué puedes hacer tú | What you can do | |
| `crew.invite.canBody` | Proponerle trabajo a quien sea, decir qué te tiene atorado, y **decidir tú el estado de lo tuyo** en la Revisión de cada semana. | Propose work to anyone, say what's got you stuck, and **make the call on your own work** in each week's Review. | |
| `crew.invite.leaveLabel` | Si algún día te vas | If you ever leave | |
| `crew.invite.leaveBody` | **Lo que hiciste en este Crew se queda aquí**, y se le pasa a alguien. Lo tuyo se va contigo. | **What you did in this Crew stays here** and gets handed to someone. Your own stuff leaves with you. | |
| `crew.invite.accept` | Aceptar y entrar | Accept and join | |
| `crew.invite.decline` | Ahora no | Not now | |
| `crew.invite.expiry` | `Caduca en {days, plural, one {# día} other {# días}}` | `Expires in {days, plural, one {# day} other {# days}}` | |
| `crew.invite.noCharge` | Entrar no cambia tu plan ni te cobra nada. Lo paga el dueño del Crew. | Joining doesn't change your plan or cost you anything. The Crew's owner covers it. | **Corregido:** quien invita puede no ser el dueño |
| `crew.invite.noAccount` | ¿Todavía no tienes cuenta de continuu.it? La creas al aceptar, con tu correo y una contraseña. El resto te lo preguntamos después, cuando entres a lo tuyo. | No continuu.it account yet? You'll create one when you accept, with just an email and a password. We'll ask the rest later, when you get to your own space. | **Corregido:** el nombre público es continuu.it |

---

## 8. El espacio personal, tocado por el Crew

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.chip.label` | {code} · {crew} | {code} · {crew} | |
| `crew.chip.aria` | Del Crew {crew} | From the {crew} Crew | |
| `crew.personal.hint` | Tu trabajo del Crew sí aparece aquí. | Your Crew work shows up here too. | |
| `crew.personal.quotaNote` | No cuenta contra tu cuota personal, y nadie del Crew ve nada de lo demás. | It doesn't count against your personal limits, and nobody in the Crew sees the rest. | **Corregido:** «tu jefe» contradecía §1.7 y reforzaba el miedo que la pantalla desactiva |

---

## 9. Errores

Van por código, no por mensaje. Ver `PLAN.md` §10.2.

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.errors.seatLimit` | Este Crew es para {seats}. {plan} llega a {max}. | This Crew is set for {seats}. {plan} goes up to {max}. | Definir si `{seats}` trae número o frase |
| `crew.errors.projectLimit` | Este Crew tiene {cap} proyectos, el tope de {plan}. Termina o mata uno, o pasa a {next}. | This Crew has {cap} projects, the {plan} limit. Finish or kill one, or move to {next}. | *Finish or kill* es léxico de marca y más preciso que «cierra» |
| `crew.errors.taskLimit` | Este Crew llegó a {cap} tareas abiertas, el tope de {plan}. Cierra algunas para añadir más. | This Crew hit {cap} open tasks, the {plan} limit. Close a few to add more. | Se le añadió la salida, en los dos idiomas |
| `crew.errors.notMember` | Ya no tienes acceso a este Crew. | You don't have access to this Crew anymore. | |
| `crew.errors.notLead` | Eso solo lo puede hacer un lead. | Only a lead can do that. | |
| `crew.errors.inviteExpired` | Esta invitación caducó. Pídele otra a quien te invitó. | This invite expired. Ask whoever sent it for a new one. | Se ve sin sesión iniciada |
| `crew.errors.inviteTaken` | Esta invitación ya se usó. | This invite was already used. | |
| `crew.errors.secondFreeCrew` | Ya tienes un Crew Micro. Los planes de pago no tienen este límite. | You already have a Micro Crew. Paid plans don't have this limit. | |

---

## 10. Solo móvil

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.mobile.tabPulse` | Pulso | Pulse | ▸ ancho: 4 pestañas en 390 px |
| `crew.mobile.tabProjects` | Proyectos | Projects | ▸ ancho |
| `crew.mobile.tabTasks` | Tareas | Tasks | ▸ ancho |
| `crew.mobile.tabMore` | Más | More | ▸ ancho |
| `crew.mobile.sheetMore` | Todo lo demás | Everything else | **Corregido:** «Los siete destinos» era nota de diseño |
| `crew.mobile.avatarLongPress` | Mantén pulsado para ver el nombre | Press and hold to see the name | No hay hover en móvil |
| `crew.mobile.reviewClose` | Se cierra sola el domingo · nadie tiene que cerrarla | Closes itself Sunday · nobody has to | ▸ ancho |

---

## 11. Lo que manda el servidor

### 11.1 Notificaciones · `core/notifications/i18n/{en,es}.py`

`str.format`, **sin ICU**. Los puntos finales van escapados como `\\.` en MarkdownV2 de Telegram.

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew.assignment.title` | {name} te asignó una tarea | {name} assigned you a task | |
| `crew.assignment.body` | {title} · vence {due} | {title} · due {due} | |
| `crew.proposal.title` | {name} te propone una tarea | {name} proposed a task | |
| `crew.proposal.body` | {title}. Tú decides si entra. | {title}. You decide if it's in. | |
| `crew.proposal.accepted` | {name} aceptó tu propuesta | {name} accepted your proposal | |
| `crew.proposal.declined` | {name} no tomó tu propuesta | {name} passed on your proposal | Sin reproche |
| `crew.review.open.title` | La Revisión de {crew} está abierta | {crew}'s Review is open | |
| `crew.review.open.body` | Proyectos que esperan tu decisión: {count}. Cierra sola el domingo. | Projects waiting on your call: {count}. It closes on its own Sunday. | **Corregido:** sin ICU hay que reestructurar para que funcione con 1 |
| `crew.review.closing.title` | La Revisión cierra hoy | The Review closes today | |
| `crew.review.cta` | Contestar | Make the call | |

### 11.2 Correo de invitación · `core/notifications/email_templates.py`

Placeholders con `{{llave}}`, doble llave.

| Clave | ES | EN | Notas |
|---|---|---|---|
| `crew_invite.subject` | {{inviter}} te quiere en {{crew}} | {{inviter}} wants you in {{crew}} | ▸ ancho: los clientes cortan cerca de 45 caracteres |
| `crew_invite.preheader` | Un espacio compartido, aparte de tu cuenta. A ti no te cuesta nada. | A shared space, separate from your account. Free for you. | |
| `crew_invite.cta` | Ver la invitación | See the invite | |
| `crew_invite.expiry` | Esta invitación caduca el {{expires_on}}. | This invite expires on {{expires_on}}. | **Corregido:** con fecha se evita el plural sin ICU |

**`crew_invite.body` (EN):**

```
Hi,

{{inviter}} invited you to {{crew}}, a Crew on continuu.it. A Crew is a shared space for
projects and tasks. It sits next to your account, not inside it.

What that means for you:

- The Crew sees the projects and tasks you keep in it. Nothing else.
- Your own projects, ideas, routines, and notes stay yours.
- You can propose work, flag what's got you stuck, and make the call on your own work each week.
- If you leave, the Crew's work stays with the Crew. Your stuff goes with you.

Joining costs you nothing. The Crew's owner covers it.

[See the invite]

{{inviter}} is waiting on you.
```

**`crew_invite.body` (ES):**

```
Hola:

{{inviter}} te invitó a {{crew}}, un Crew en continuu.it. Un Crew es un espacio compartido
para proyectos y tareas. Va al lado de tu cuenta, no dentro.

Qué significa para ti:

- El Crew ve los proyectos y tareas que tengas ahí. Nada más.
- Tus proyectos, ideas, rutinas y notas siguen siendo tuyos.
- Puedes proponer trabajo, decir qué te tiene atorado, y decidir tú el estado de lo tuyo cada semana.
- Si te vas, el trabajo del Crew se queda con el Crew. Lo tuyo se va contigo.

Entrar no te cuesta nada. Lo paga el dueño del Crew.

[Ver la invitación]

{{inviter}} te está esperando.
```

---

## 12. Datos de ejemplo (reescritos, no traducidos)

Las capturas de `docs/ayuda` se generan por idioma, así que la versión inglesa necesita su
propio juego. Numerales en lugar de palabras, por la regla 10 de la guía de voz.

| ES | EN | Notas |
|---|---|---|
| Estudio Norte (**EN**) | North Studio (**NS**) | El código de dos letras cambia, y de paso evita que «EN» se confunda con el idioma |
| Ana Ruiz (AR) · Beto Lara (BL) | Anna Reed (AR) · Ben Lane (BL) | Mismas iniciales: los avatares de las capturas no cambian |
| Migración de facturación · Campaña de septiembre · Onboarding de clientes | Billing migration · September campaign · Client onboarding | |
| Cerrar el mapeo de productos · Enviar contrato revisado · Grabar el video de bienvenida | Finish the product mapping · Send the revised contract · Record the welcome video | |
| «El cliente se cambió de CRM. Dos meses de trabajo que ya no aplican.» | "Client switched CRMs. 2 months of work that doesn't apply anymore." | |
| «Existe una que cuesta nueve dólares al mes. Construirla era orgullo.» | "There's one that costs $9 a month. Building our own was pride." | |
| «Tres números en seis meses. Fingir que seguía viva nos costaba culpa cada lunes.» | "3 issues in 6 months. Pretending it was still alive cost us guilt every Monday." | |
| «Lo empecé para no hacer el trabajo del cliente. Esa es toda la razón.» | "I started it to avoid doing the client's work. That's the whole reason." | |
| «Grabamos dos. Nadie los escuchó, nosotros incluidos.» | "We recorded 2 episodes. Nobody listened. Not even us." | *episodes* aclara que era un podcast |
| Aprendimos: preguntar por el roadmap del cliente antes de integrar nada. | We learned: ask about the client's roadmap before integrating anything. | |


diff-base:
	meld res-demo-original/bi.yaml res-demo-with-cidr/bi.yaml &
	meld res-demo-original/keycloak.yaml res-demo-with-cidr/keycloak.yaml &
	meld res-demo-original/res-sso-keycloak.yaml res-demo-with-cidr/res-sso-keycloak.yaml &
	# meld res-demo-original/res.ldif res-demo-with-cidr/res.ldif &

diff-top:
	meld res-demo-original/res-demo-stack.yaml res-demo-with-cidr/res-demo-stack.yaml &
	meld res-demo-with-cidr/res-demo-stack.yaml res-demo-with-cidr/res-bi-only.yaml &
	meld res-demo-with-cidr/res-demo-stack.yaml res-demo-with-cidr/res-only.yaml &

diff: diff-base diff-top

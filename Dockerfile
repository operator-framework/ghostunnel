FROM openshift/origin-release:golang-1.13 as build

COPY . /go/src/github.com/square/ghostunnel

RUN CGO_ENABLED=0 go build -tags nopkcs11 -o /usr/bin/ghostunnel github.com/square/ghostunnel

FROM openshift/origin-base

COPY --from=build /usr/bin/ghostunnel /usr/bin/ghostunnel

ENTRYPOINT ["/usr/bin/ghostunnel"]

LABEL io.k8s.display-name="OpenShift Ghostunnel" \
      io.k8s.description="This is an image used by metering-operator to to install and run Ghostunnel." \
      io.openshift.tags="openshift" \
      maintainer="<metering-team@redhat.com>"
